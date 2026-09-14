/* Passport hook sender: bounded same-host IPC, no interpreter or event storage.
 * The receiver captures the transcript position before acknowledging the input.
 * Only its metadata frames cross SSH. Every outcome returns neutral hook output.
 */
#define _POSIX_C_SOURCE 200809L
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define MAX_INPUT 1000000u
#define IPC_TIMEOUT_MS 50

static int64_t milliseconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return 0;
    return (int64_t)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static int ready(int fd, short events, int64_t deadline) {
    for (;;) {
        int64_t remaining = deadline - milliseconds();
        if (remaining <= 0) return 0;
        struct pollfd p = {.fd = fd, .events = events, .revents = 0};
        int result = poll(&p, 1, (int)remaining);
        if (result < 0 && errno == EINTR) continue;
        return result > 0 && (p.revents & events);
    }
}

static int write_all(int fd, const void *data, size_t size, int64_t deadline) {
    const unsigned char *bytes = data;
    while (size) {
        if (!ready(fd, POLLOUT, deadline)) return 0;
        ssize_t n = write(fd, bytes, size);
        if (n < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (n <= 0) return 0;
        bytes += n;
        size -= (size_t)n;
    }
    return 1;
}

static void send_event(const char *path) {
    static unsigned char input[MAX_INPUT + 1];
    size_t size = 0;
    /* Codex closes stdin after writing its payload. Bound malformed/large input. */
    int64_t input_deadline = milliseconds() + 1000;
    for (;;) {
        if (!ready(STDIN_FILENO, POLLIN | POLLHUP, input_deadline)) return;
        ssize_t n = read(STDIN_FILENO, input + size, sizeof(input) - size);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) return;
        if (n == 0) break;
        size += (size_t)n;
        if (size > MAX_INPUT) return;
    }
    if (!size) return;
    struct sockaddr_un address;
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    if (strlen(path) >= sizeof(address.sun_path)) return;
    memcpy(address.sun_path, path, strlen(path) + 1);
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return;
    if (fcntl(fd, F_SETFL, O_NONBLOCK) < 0) goto done;
    /* Unix connect is immediate; a full listener backlog drops this event. */
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) != 0) goto done;
    int64_t deadline = milliseconds() + IPC_TIMEOUT_MS;
    uint32_t length = htonl((uint32_t)size);
    if (!write_all(fd, &length, sizeof(length), deadline)) goto done;
    if (!write_all(fd, input, size, deadline)) goto done;
    if (ready(fd, POLLIN, deadline)) {
        unsigned char ack;
        (void)read(fd, &ack, 1);
    }
done:
    close(fd);
}

int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);
    char path[4096];
    const char *destination = NULL;
    if (argc == 3 && strcmp(argv[1], "--socket") == 0) {
        destination = argv[2];
    } else if (argc == 1) {
        const char *home = getenv("CODEX_HOME");
        int n;
        if (home && *home) {
            n = snprintf(path, sizeof(path), "%s/passport/events.sock", home);
        } else {
            home = getenv("HOME");
            n = home ? snprintf(path, sizeof(path), "%s/.codex/passport/events.sock", home) : -1;
        }
        if (n > 0 && (size_t)n < sizeof(path)) destination = path;
    }
    if (destination) send_event(destination);
    (void)write(STDOUT_FILENO, "{}\n", 3);
    return 0;
}
