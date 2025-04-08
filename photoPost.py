import requests
import argparse
import os

BASE_URL = "http://localhost:5000"

def send_image(image_path):
    if not os.path.exists(image_path):
        print(f"Error: File '{image_path}' does not exist.")
        return

    with open(image_path, 'rb') as image_file:
        files = {'image': image_file}
        response = requests.post(f"{BASE_URL}/api/image", files=files)
        if response.status_code == 200:
            print("Image successfully sent:", response.json())
        else:
            print("Error while sending image:", response.status_code, response.text)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send an image to the server.")
    parser.add_argument("-i", "--image", required=True, help="Path to the image file to send.")
    args = parser.parse_args()

    send_image(args.image)