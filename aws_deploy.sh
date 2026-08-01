#!/bin/bash
set -e

echo "========================================="
echo "Political Alpha Tracker - AWS Deployment"
echo "========================================="

# 1. System Updates
echo "[1/4] Updating system packages..."
sudo apt-get update -y
sudo apt-get upgrade -y

# 2. Install Docker & Docker Compose if not present
if ! command -v docker &> /dev/null
then
    echo "[2/4] Installing Docker..."
    sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    
    # Add ubuntu user to docker group
    sudo usermod -aG docker ubuntu
    echo "Docker installed successfully. Note: You may need to log out and log back in for docker group changes to take effect."
else
    echo "[2/4] Docker is already installed. Skipping."
fi

# 3. Create necessary directories
echo "[3/4] Preparing directories..."
mkdir -p data
touch .env

# 4. Build the Docker Image
echo "[4/4] Building the Docker container..."
sudo docker build -t alpha-tracker .

echo "========================================="
echo "✅ Setup Complete!"
echo "Next Steps:"
echo "1. Nano into .env and paste your GEMINI_API_KEY and TELEGRAM_BOT_TOKEN: nano .env"
echo "2. Set up the cron job to run the container daily at 5:00 PM IST."
echo "   Run 'crontab -e' and copy the contents from crontab_setup.txt."
echo "========================================="
