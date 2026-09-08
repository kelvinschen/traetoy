fn main() {
    cc::Build::new().file("src/text.c").compile("passport_text");
    cc::Build::new()
        .file("src/ble_macos.m")
        .flag("-fobjc-arc")
        .flag("-fblocks")
        .compile("passport_bluetooth");
    let plist =
        std::path::PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").unwrap()).join("Info.plist");
    println!(
        "cargo:rustc-link-arg=-Wl,-sectcreate,__TEXT,__info_plist,{}",
        plist.display()
    );
    println!("cargo:rerun-if-changed=src/ble_macos.m");
    println!("cargo:rerun-if-changed=Info.plist");
    for framework in [
        "CoreText",
        "CoreGraphics",
        "CoreFoundation",
        "Foundation",
        "CoreBluetooth",
    ] {
        println!("cargo:rustc-link-lib=framework={framework}");
    }
    println!("cargo:rerun-if-changed=src/text.c");
}
