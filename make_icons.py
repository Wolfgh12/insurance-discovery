from PIL import Image

# 1. Load the clean shield image
try:
    img = Image.open('new_icon.jpg').convert('RGBA')
except FileNotFoundError:
    print("Error: Please make sure 'new_icon.jpg' is saved in this folder.")
    exit()

# 2. Crop from the center to make it a perfect square
width, height = img.size
min_dim = min(width, height)
left = (width - min_dim) // 2
top = (height - min_dim) // 2
right = (width + min_dim) // 2
bottom = (height + min_dim) // 2
square_img = img.crop((left, top, right, bottom))

# 3. Export the 512x512 High-Res Icon
icon_512 = square_img.resize((512, 512), Image.Resampling.LANCZOS)
icon_512.save('static/images/icon-512.png', 'PNG')
print("✅ Successfully generated: static/images/icon-512.png")

# 4. Export the 192x192 Standard Icon
icon_192 = square_img.resize((192, 192), Image.Resampling.LANCZOS)
icon_192.save('static/images/icon-192.png', 'PNG')
print("✅ Successfully generated: static/images/icon-192.png")