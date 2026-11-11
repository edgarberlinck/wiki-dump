FROM python:3.14-slim

WORKDIR /app

# Copy project files
COPY dump.py requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# The shell expands SUBJECT while keeping multi-word subjects together.
CMD ["sh", "-c", "exec python /app/dump.py \"${SUBJECT:-The Ramones}\""]