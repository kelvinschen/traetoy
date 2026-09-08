#include "companion_ble.h"
#include "companion_ble_wire.h"
#include "nvs_flash.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "mbedtls/gcm.h"
#include "mbedtls/md.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

/* A32D1000-3B47-4A84-9E3F-217158CD0001; distinct from factory recovery FFF0. */
#define UUID(last) BLE_UUID128_INIT(0x01,0x00,0xcd,0x58,0x71,0x21,0x3f,0x9e,0x84,0x4a,0x47,0x3b,last,0x10,0x2d,0xa3)
/* Application authentication errors must not trigger OS SMP/bonding prompts. */
#define COMPANION_ATT_AUTH_FAILED 0x80
static const ble_uuid128_t service_uuid=UUID(0x00),info_uuid=UUID(0x01),rx_uuid=UUID(0x02),tx_uuid=UUID(0x03);
static SemaphoreHandle_t guard;
static uint8_t psk[32],info[28],rx_key[32],tx_key[32],reply[320],addr_type;
static uint16_t reply_size,connection=BLE_HS_CONN_HANDLE_NONE;
static uint32_t session,last_counter;
static bool paired;
static int64_t activity;
static companion_ble_frame_t frame;
static char plain[7168];
static companion_ble_receive_fn receive_line;
static char name[24];
static int gap_event(struct ble_gap_event *event,void *arg);
static uint32_t be32(const uint8_t *p){return (uint32_t)p[0]<<24|(uint32_t)p[1]<<16|(uint32_t)p[2]<<8|p[3];}
static void put32(uint8_t *p,uint32_t n){p[0]=n>>24;p[1]=n>>16;p[2]=n>>8;p[3]=n;}
static void derive(const char *label,uint8_t *out) {
    uint8_t data[64];size_t n=strlen(label);memcpy(data,label,n);memcpy(data+n,info+10,16);
    ESP_ERROR_CHECK(mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),psk,32,data,n+16,out));
}
static int advertise(void) {
    struct ble_hs_adv_fields fields={0};fields.flags=BLE_HS_ADV_F_DISC_GEN|BLE_HS_ADV_F_BREDR_UNSUP;
    fields.uuids128=(ble_uuid128_t *)&service_uuid;fields.num_uuids128=1;fields.uuids128_is_complete=1;
    int rc=ble_gap_adv_set_fields(&fields);if(rc)return rc;
    struct ble_hs_adv_fields scan={0};scan.name=(uint8_t *)name;scan.name_len=strlen(name);scan.name_is_complete=1;
    rc=ble_gap_adv_rsp_set_fields(&scan);if(rc)return rc;
    struct ble_gap_adv_params params={0};params.conn_mode=BLE_GAP_CONN_MODE_UND;params.disc_mode=BLE_GAP_DISC_MODE_GEN;
    params.itvl_min=320;params.itvl_max=480;
    return ble_gap_adv_start(addr_type,NULL,BLE_HS_FOREVER,&params,gap_event,NULL);
}
static int gap_event(struct ble_gap_event *e,void *arg) {
    (void)arg;
    if(e->type==BLE_GAP_EVENT_CONNECT && !e->connect.status) {
        xSemaphoreTake(guard,portMAX_DELAY);connection=e->connect.conn_handle;session++;if(!session)session=1;
        esp_fill_random(info+10,16);derive("passport-ble-v1-rx",rx_key);derive("passport-ble-v1-tx",tx_key);
        last_counter=0;reply_size=0;frame.used=frame.total=0;activity=esp_timer_get_time();xSemaphoreGive(guard);
        struct ble_gap_upd_params params={.itvl_min=12,.itvl_max=24,.latency=0,.supervision_timeout=400,.min_ce_len=0,.max_ce_len=0};
        ble_gap_update_params(connection,&params);
        printf("CDX_BLE connected session=%lu\n",(unsigned long)session);
    } else if(e->type==BLE_GAP_EVENT_CONN_UPDATE) {
        struct ble_gap_conn_desc desc;
        if(!ble_gap_conn_find(e->conn_update.conn_handle,&desc))
            printf("CDX_BLE parameters interval_us=%u latency=%u status=%d\n",desc.conn_itvl*1250u,desc.conn_latency,e->conn_update.status);
    } else if(e->type==BLE_GAP_EVENT_DISCONNECT) {
        xSemaphoreTake(guard,portMAX_DELAY);connection=BLE_HS_CONN_HANDLE_NONE;reply_size=0;frame.used=0;xSemaphoreGive(guard);
        printf("CDX_BLE disconnected reason=%d\n",e->disconnect.reason);advertise();
    } else if((e->type==BLE_GAP_EVENT_CONNECT && e->connect.status)||e->type==BLE_GAP_EVENT_ADV_COMPLETE)advertise();
    return 0;
}
static int access_characteristic(uint16_t conn,uint16_t attr,struct ble_gatt_access_ctxt *ctx,void *arg) {
    (void)attr;uintptr_t kind=(uintptr_t)arg;
    if(!xSemaphoreTake(guard,pdMS_TO_TICKS(100)))return BLE_ATT_ERR_INSUFFICIENT_RES;
    int rc=0;
    if(conn!=connection || !paired){rc=COMPANION_ATT_AUTH_FAILED;goto done;}
    if(kind==1 && ctx->op==BLE_GATT_ACCESS_OP_READ_CHR){uint16_t mtu=ble_att_mtu(conn);info[26]=mtu>>8;info[27]=mtu;rc=os_mbuf_append(ctx->om,info,sizeof(info))?BLE_ATT_ERR_INSUFFICIENT_RES:0;goto done;}
    if(kind==3 && ctx->op==BLE_GATT_ACCESS_OP_READ_CHR){rc=os_mbuf_append(ctx->om,reply,reply_size)?BLE_ATT_ERR_INSUFFICIENT_RES:0;goto done;}
    if(kind!=2||ctx->op!=BLE_GATT_ACCESS_OP_WRITE_CHR){rc=BLE_ATT_ERR_WRITE_NOT_PERMITTED;goto done;}
    uint8_t chunk[512];uint16_t length=OS_MBUF_PKTLEN(ctx->om);
    if(length>sizeof(chunk)||ble_hs_mbuf_to_flat(ctx->om,chunk,sizeof(chunk),NULL)){rc=BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;goto done;}
    int result=companion_ble_fragment(&frame,chunk,length);
    if(result<0){rc=BLE_ATT_ERR_INVALID_OFFSET;goto done;}if(!result)goto done;
    uint32_t counter=be32(frame.bytes);size_t size=frame.total-20;
    if(size>sizeof(plain)){rc=BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;goto done;}
    if(!counter||counter<=last_counter){rc=COMPANION_ATT_AUTH_FAILED;goto done;}
    uint8_t iv[12]={0};put32(iv+8,counter);mbedtls_gcm_context gcm;mbedtls_gcm_init(&gcm);
    rc=mbedtls_gcm_setkey(&gcm,MBEDTLS_CIPHER_ID_AES,rx_key,256);
    if(!rc)rc=mbedtls_gcm_auth_decrypt(&gcm,size,iv,sizeof(iv),NULL,0,frame.bytes+4+size,16,frame.bytes+4,(uint8_t *)plain);
    mbedtls_gcm_free(&gcm);
    if(rc){rc=COMPANION_ATT_AUTH_FAILED;goto done;}
    if(companion_ble_unpack((uint8_t *)plain,size,(char *)frame.bytes,sizeof(frame.bytes))<0){rc=BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;goto done;}
    last_counter=counter;reply_size=0;activity=esp_timer_get_time();uint32_t request_session=session;
    xSemaphoreGive(guard);
    /* This callback only parses/enqueues; LVGL and response encryption run in the UI task. */
    if(!receive_line((char *)frame.bytes,request_session,counter))companion_ble_reply(request_session,counter,"CDX_ERR invalid_or_busy");
    return 0;
done:
    xSemaphoreGive(guard);return rc;
}
static const struct ble_gatt_svc_def services[]={
    {.type=BLE_GATT_SVC_TYPE_PRIMARY,.uuid=&service_uuid.u,.characteristics=(struct ble_gatt_chr_def[]){
        {.uuid=&info_uuid.u,.access_cb=access_characteristic,.arg=(void *)1,.flags=BLE_GATT_CHR_F_READ},
        {.uuid=&rx_uuid.u,.access_cb=access_characteristic,.arg=(void *)2,.flags=BLE_GATT_CHR_F_WRITE},
        {.uuid=&tx_uuid.u,.access_cb=access_characteristic,.arg=(void *)3,.flags=BLE_GATT_CHR_F_READ},
        {0}}},{0}};
static void synchronized(void){int rc=ble_hs_util_ensure_addr(0);if(!rc)rc=ble_hs_id_infer_auto(0,&addr_type);if(!rc)rc=advertise();printf("CDX_BLE advertising=%d paired=%d\n",rc,paired);}
static void host_task(void *arg){(void)arg;nimble_port_run();nimble_port_freertos_deinit();}
esp_err_t companion_ble_start(companion_ble_receive_fn receive) {
    receive_line=receive;guard=xSemaphoreCreateMutex();if(!guard)return ESP_ERR_NO_MEM;
    esp_err_t rc=nvs_flash_init();if(rc!=ESP_OK)return rc;
    nvs_handle_t nvs;if(nvs_open("codex_ble",NVS_READONLY,&nvs)==ESP_OK){size_t n=32;paired=nvs_get_blob(nvs,"psk",psk,&n)==ESP_OK&&n==32;nvs_close(nvs);}
    memcpy(info,"CPB1",4);ESP_ERROR_CHECK(esp_read_mac(info+4,ESP_MAC_BT));
    snprintf(name,sizeof(name),"Codex-%02x%02x%02x",info[7],info[8],info[9]);
    rc=nimble_port_init();if(rc!=ESP_OK)return rc;
    ble_svc_gap_init();ble_svc_gatt_init();ble_svc_gap_device_name_set(name);
    if(ble_gatts_count_cfg(services)||ble_gatts_add_svcs(services))return ESP_FAIL;
    ble_hs_cfg.sync_cb=synchronized;nimble_port_freertos_init(host_task);return ESP_OK;
}
bool companion_ble_provision(const char *hex,char identity[13]) {
    if(!guard){printf("CDX_BLE pair_guard=missing\n");return false;}
    if(strlen(hex)!=64){printf("CDX_BLE pair_length=%u\n",(unsigned)strlen(hex));return false;}
    uint8_t key[32];
    for(int i=0;i<32;i++){char part[3]={hex[i*2],hex[i*2+1],0};char *end;long n=strtol(part,&end,16);if(*end||n<0||n>255){printf("CDX_BLE pair_hex_index=%d\n",i);return false;}key[i]=(uint8_t)n;}
    nvs_handle_t nvs;esp_err_t opened=nvs_open("codex_ble",NVS_READWRITE,&nvs);
    if(opened!=ESP_OK){printf("CDX_BLE pair_open=%s\n",esp_err_to_name(opened));return false;}
    esp_err_t rc=nvs_set_blob(nvs,"psk",key,sizeof(key));if(rc==ESP_OK)rc=nvs_commit(nvs);nvs_close(nvs);if(rc!=ESP_OK){printf("CDX_BLE pair_commit=%s\n",esp_err_to_name(rc));return false;}
    xSemaphoreTake(guard,portMAX_DELAY);memcpy(psk,key,sizeof(psk));paired=true;uint16_t conn=connection;
    for(int i=0;i<6;i++)snprintf(identity+i*2,3,"%02x",info[4+i]);
    xSemaphoreGive(guard);
    if(conn!=BLE_HS_CONN_HANDLE_NONE)ble_gap_terminate(conn,BLE_ERR_REM_USER_CONN_TERM);
    memset(key,0,sizeof(key));return true;
}
void companion_ble_reply(uint32_t request_session,uint32_t counter,const char *line) {
    if(!guard||strlen(line)>sizeof(reply)-20)return;
    xSemaphoreTake(guard,portMAX_DELAY);
    if(request_session==session&&connection!=BLE_HS_CONN_HANDLE_NONE) {
        uint8_t iv[12]={0};put32(iv+8,counter);put32(reply,counter);size_t n=strlen(line);
        mbedtls_gcm_context gcm;mbedtls_gcm_init(&gcm);
        int rc=mbedtls_gcm_setkey(&gcm,MBEDTLS_CIPHER_ID_AES,tx_key,256);
        if(!rc)rc=mbedtls_gcm_crypt_and_tag(&gcm,MBEDTLS_GCM_ENCRYPT,n,iv,sizeof(iv),NULL,0,(uint8_t *)line,reply+4,16,reply+4+n);
        mbedtls_gcm_free(&gcm);reply_size=rc?0:n+20;
    }xSemaphoreGive(guard);
}
void companion_ble_tick(void) {
    if(!guard)return;
    uint16_t conn=BLE_HS_CONN_HANDLE_NONE;
    if(xSemaphoreTake(guard,0)){if(connection!=BLE_HS_CONN_HANDLE_NONE&&esp_timer_get_time()-activity>(last_counter?20000000:10000000)){conn=connection;activity=esp_timer_get_time();}xSemaphoreGive(guard);}
    if(conn!=BLE_HS_CONN_HANDLE_NONE)ble_gap_terminate(conn,BLE_ERR_REM_USER_CONN_TERM);
}

bool companion_ble_connected(void) {
    if(!guard)return false;
    xSemaphoreTake(guard,portMAX_DELAY);
    bool connected=connection!=BLE_HS_CONN_HANDLE_NONE && last_counter>0;
    xSemaphoreGive(guard);return connected;
}
