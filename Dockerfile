# ==========================================
# STAGE 1: Builder (Install Dependencies)
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies to /root/.local
RUN pip install --user --no-cache-dir -r requirements.txt


# ==========================================
# STAGE 2: Final Runtime
# ==========================================
FROM python:3.11-slim

WORKDIR /app

# 1. Create the non-root user first
RUN useradd -m -u 1000 appuser

# 2. Copy the dependencies from the 'builder' stage
# We copy them directly to the appuser's home folder so we don't need 'chown' hacks on /root
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

# 3. Copy application code and assign ownership to appuser immediately
COPY --chown=appuser:appuser . .

# 4. Update PATH so Python finds the packages in the new location
ENV PATH=/home/appuser/.local/bin:$PATH

# 5. Switch to non-root user
USER appuser

# Expose port
EXPOSE 8000

# Health check
# Note: Ensure 'httpx' is listed in your requirements.txt for this to work
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')" || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]