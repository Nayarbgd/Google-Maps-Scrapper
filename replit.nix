{pkgs}: {
  deps = [
    pkgs.expat
    pkgs.dbus
    pkgs.nss
    pkgs.nspr
    pkgs.cups
    pkgs.at-spi2-atk
    pkgs.alsa-lib
    pkgs.cairo
    pkgs.pango
    pkgs.mesa
    pkgs.libdrm
    pkgs.libxkbcommon
    pkgs.xorg.libXrandr
    pkgs.xorg.libXfixes
    pkgs.xorg.libXext
    pkgs.xorg.libXdamage
    pkgs.xorg.libXcomposite
    pkgs.xorg.libX11
    pkgs.xorg.libxcb
    pkgs.chromium
  ];
}
