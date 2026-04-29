FROM node:20-slim

# Install Python 3.11
RUN apt-get update \
    && apt-get install -y python3.11 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies and prepare
RUN npm ci
RUN npm run prepare

# Copy application code
COPY . .

# Build the application
RUN npm run build

# Set the start command
CMD ["node", "build/index.js"]
