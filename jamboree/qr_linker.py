import qrcode

#  • Option A: point to the raw URL
url = "https://raw.githubusercontent.com/askjake/JAMboreeLite/main/install_jamboreeLite.bat"

#  • Option B: embed the full script text (larger QR)
#with open("install_jamboreeLite.bat","r") as f:
#    url = f.read()

# Generate QR
qr = qrcode.QRCode(
    version=None,
    error_correction=qrcode.constants.ERROR_CORRECT_L,
    box_size=10,
    border=4,
)
qr.add_data(url)
qr.make(fit=True)
img = qr.make_image()

# Save out
img.save("install_jamboreeLite_qr.png")
print("Wrote install_jamboreeLite_qr.png. Scan with any smartphone.")
