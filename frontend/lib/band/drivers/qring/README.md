# QRing smart ring driver

Takes heart rate, SpO2, blood pressure and body temperature from a QC Wireless
"QRing" ring over Web Bluetooth, so the kiosk needs no app on the machine.

- `qring_protocol.dart`: the Bluetooth packets, read from the vendor's Android
  SDK (`SDK/QRing_Android_SDK_1.0.0.57`). Each constant names the SDK class it
  comes from, so it can be checked against a newer SDK.
- `qring_band.dart`: the measurement run (`QRingBand implements BandService`):
  connect, sync the time and read what the ring can measure, then measure each
  supported vital in turn, 30 s each as the SDK does, keeping only plausible
  readings, and disconnect.

The vendor's native SDKs (Android `.aar`, iOS `.framework`) are not used: the
kiosk is a web app. They would be the route if the kiosk became a native app.

Using it:

- Chrome or Edge, on https or localhost. On Linux, start Chrome with
  `--enable-experimental-web-platform-features` (`tool/chrome.sh` does).
- The first measurement opens Chrome's device chooser: pick the ring and press
  Pair. The ring is then remembered for later patients on that kiosk.
- A ring connected to a phone (the QRing app) does not advertise and will not
  appear: disconnect it from the phone first.

Replacing this band: add another folder under `drivers/` implementing
`BandService` and change the one line in `band/band_registry.dart`. To remove it,
delete this folder and that line.
