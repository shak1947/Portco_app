# Form ADV RAG System - Deployment Guide

Complete instructions for deploying to production. Pick your platform.

---

## Option 1: Vercel (Recommended - Easiest)

### Prerequisites
- Vercel account (free at vercel.com)
- GitHub repository

### Steps

1. **Create GitHub Repository**
   ```bash
   git init
   git add .
   git commit -m "RAG system initial commit"
   git remote add origin https://github.com/yourusername/form-adv-rag
   git push -u origin main
   ```

2. **Create Vercel Config** (`vercel.json`)
   ```json
   {
     "buildCommand": "pip install -r requirements.txt",
     "outputDirectory": ".",
     "framework": "python",
     "functions": {
       "app.py": {
         "memory": 1024,
         "maxDuration": 30
       }
     }
   }
   ```

3. **Update Flask for Serverless** (`app.py`)
   ```python
   from flask import Flask
   
   app = Flask(__name__)
   
   # ... rest of app code ...
   
   # For Vercel serverless
   from vercel_python_wsgi import asgi_to_asgi_cgi
   ```

4. **Deploy to Vercel**
   ```bash
   npm i -g vercel
   vercel
   ```

5. **Set Environment Variables**
   - Go to Vercel Dashboard → Settings → Environment Variables
   - Add:
     - `OPENAI_API_KEY`
     - `ANTHROPIC_API_KEY`

6. **Upload Data** (Optional - skip for stateless)
   - If keeping vector store, need persistent storage
   - Otherwise, load from S3/cloud storage at runtime

**Pros:**
- ✅ Automatic deployments from Git
- ✅ Built-in monitoring
- ✅ Free tier available
- ✅ Scales automatically
- ✅ Custom domains included

**Cons:**
- ❌ Serverless constraints (30 second timeout max)
- ❌ Data must be uploaded separately (vector store)
- ❌ Limited local file persistence

**Cost:** $0-20/month (free tier sufficient for 100 queries/day)

---

## Option 2: Docker + AWS EC2 (Recommended for Scale)

### Prerequisites
- AWS account
- Docker installed locally

### Steps

1. **Create Dockerfile**
   ```dockerfile
   FROM python:3.11-slim

   WORKDIR /app

   # Install dependencies
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt

   # Copy application
   COPY app.py .
   COPY src/ ./src/
   COPY templates/ ./templates/
   COPY Data/ ./Data/
   COPY .env .

   # Expose port
   EXPOSE 5000

   # Health check
   HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
     CMD curl -f http://localhost:5000/api/health || exit 1

   # Run
   CMD ["python", "app.py"]
   ```

2. **Create Docker Compose** (`docker-compose.yml`)
   ```yaml
   version: '3.8'
   services:
     rag-api:
       build: .
       ports:
         - "5000:5000"
       environment:
         - OPENAI_API_KEY=${OPENAI_API_KEY}
         - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
         - FLASK_ENV=production
       volumes:
         - ./Data:/app/Data
       restart: unless-stopped
   ```

3. **Build Docker Image**
   ```bash
   docker build -t form-adv-rag .
   docker run -p 5000:5000 \
     -e OPENAI_API_KEY=sk-xxx \
     -e ANTHROPIC_API_KEY=sk-ant-xxx \
     form-adv-rag
   ```

4. **Push to AWS ECR**
   ```bash
   aws ecr get-login-password --region us-east-1 | \
     docker login --username AWS --password-stdin 123456789.dkr.ecr.us-east-1.amazonaws.com
   
   docker tag form-adv-rag:latest 123456789.dkr.ecr.us-east-1.amazonaws.com/form-adv-rag:latest
   docker push 123456789.dkr.ecr.us-east-1.amazonaws.com/form-adv-rag:latest
   ```

5. **Deploy to EC2**
   ```bash
   # SSH into EC2
   ssh -i key.pem ec2-user@instance-ip
   
   # Install Docker
   sudo yum install docker
   sudo systemctl start docker
   
   # Pull and run
   sudo docker pull 123456789.dkr.ecr.us-east-1.amazonaws.com/form-adv-rag:latest
   sudo docker run -d -p 80:5000 \
     -e OPENAI_API_KEY=sk-xxx \
     -e ANTHROPIC_API_KEY=sk-ant-xxx \
     123456789.dkr.ecr.us-east-1.amazonaws.com/form-adv-rag:latest
   ```

6. **Add SSL with Nginx**
   ```nginx
   server {
     listen 443 ssl http2;
     server_name api.example.com;
     
     ssl_certificate /etc/letsencrypt/live/api.example.com/fullchain.pem;
     ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;
     
     location / {
       proxy_pass http://localhost:5000;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
     }
   }
   ```

**Pros:**
- ✅ Full control over environment
- ✅ No serverless constraints
- ✅ Can use all 9K+ chunks
- ✅ Persistent vector store locally
- ✅ Horizontal scaling with load balancer

**Cons:**
- ❌ More setup required
- ❌ Need to manage infrastructure
- ❌ Higher cost than serverless

**Cost:** $5-30/month (t3.micro free tier, or t3.small $8/month)

---

## Option 3: Railway (Balanced)

### Prerequisites
- Railway account (free at railway.app)
- GitHub connected

### Steps

1. **Connect GitHub**
   - Go to Railway.app Dashboard
   - Click "New Project"
   - Select GitHub repository
   - Click "Deploy"

2. **Set Environment Variables**
   - Project Settings → Variables
   - Add `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`

3. **Configure Python**
   - Railway auto-detects `requirements.txt`
   - Sets `PORT` automatically

4. **Update Flask**
   ```python
   import os
   
   port = int(os.environ.get('PORT', 5000))
   app.run(host='0.0.0.0', port=port)
   ```

5. **Deploy**
   ```bash
   git push origin main
   # Railway auto-deploys!
   ```

**Pros:**
- ✅ Easier than AWS
- ✅ Auto-deployment from Git
- ✅ Persistent storage available
- ✅ Free tier with $5/month credits
- ✅ PostgreSQL support if needed

**Cons:**
- ❌ Less mature than Vercel
- ❌ Less ecosystem

**Cost:** $0-5/month (free tier sufficient)

---

## Option 4: DigitalOcean App Platform

### Prerequisites
- DigitalOcean account

### Steps

1. **Create App**
   - Go to DigitalOcean → Apps
   - Click "Create App"
   - Select GitHub repository

2. **Configure**
   ```yaml
   name: form-adv-rag
   services:
   - name: api
     github:
       repo: yourusername/form-adv-rag
       branch: main
     build_command: pip install -r requirements.txt
     run_command: python app.py
     http_port: 5000
     envs:
     - key: OPENAI_API_KEY
       scope: RUN_AND_BUILD_TIME
     - key: ANTHROPIC_API_KEY
       scope: RUN_AND_BUILD_TIME
   ```

3. **Add Environment Variables**
   - Click "Edit" → "Envs"
   - Add API keys

4. **Deploy**
   - Click "Deploy" button

**Pros:**
- ✅ Simple one-click deployment
- ✅ Includes database if needed
- ✅ Good documentation
- ✅ $5/month minimum tier

**Cost:** $5-15/month

---

## Option 5: Lambda + API Gateway (Serverless at Scale)

### Prerequisites
- AWS account
- AWS CLI installed

### Steps

1. **Create Lambda Function**
   ```bash
   mkdir lambda-package
   cd lambda-package
   pip install -r requirements.txt -t .
   cp app.py .
   cp -r src templates Data .
   zip -r ../function.zip .
   ```

2. **Upload to Lambda**
   ```bash
   aws lambda create-function \
     --function-name form-adv-rag \
     --runtime python3.11 \
     --role arn:aws:iam::YOUR_ACCOUNT:role/lambda-role \
     --handler app.app \
     --zip-file fileb://function.zip \
     --memory-size 1024 \
     --timeout 30 \
     --environment Variables={OPENAI_API_KEY=sk-xxx,ANTHROPIC_API_KEY=sk-ant-xxx}
   ```

3. **Create API Gateway**
   ```bash
   aws apigateway create-rest-api \
     --name form-adv-rag-api \
     --description "Form ADV RAG API"
   ```

4. **Configure Routes**
   - /api/query → POST to Lambda
   - /api/health → GET to Lambda
   - / → Static S3

5. **Deploy**
   ```bash
   aws apigateway create-deployment \
     --rest-api-id YOUR_API_ID \
     --stage-name prod
   ```

**Pros:**
- ✅ Pay-per-request pricing
- ✅ Scales to millions of requests
- ✅ No server management

**Cons:**
- ❌ Vector store persistence tricky
- ❌ Slower cold starts
- ❌ More AWS complexity

**Cost:** $0-50/month depending on usage

---

## Option 6: Render (Simplest Free Option)

### Prerequisites
- Render account (free at render.com)
- GitHub connected

### Steps

1. **Create Web Service**
   - Go to Render Dashboard
   - Click "New +" → "Web Service"
   - Connect GitHub

2. **Configure**
   - **Name:** form-adv-rag
   - **Runtime:** Python 3.11
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python app.py`

3. **Environment Variables**
   - Add `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`

4. **Deploy**
   - Render auto-deploys on git push

**Pros:**
- ✅ Completely free tier
- ✅ Easiest setup
- ✅ Auto-deployments
- ✅ HTTPS included

**Cons:**
- ❌ Spins down after 15 min inactivity
- ❌ Limited free tier resources
- ❌ Need to upgrade for production

**Cost:** $0 (free tier) or $7/month (paid)

---

## Comparison Table

| Platform | Setup Difficulty | Cost | Scalability | Best For |
|----------|-----------------|------|------------|----------|
| **Vercel** | Easy | $0-20 | Serverless | API + Frontend |
| **Railway** | Easy | $0-5 | Medium | Development |
| **Render** | Easy | $0-7 | Medium | Testing |
| **DigitalOcean** | Medium | $5-15 | Good | Stable workloads |
| **AWS EC2** | Hard | $5-30 | Excellent | Production scale |
| **AWS Lambda** | Hard | $0-100 | Excellent | Extreme scale |

---

## Recommended Setup for Different Use Cases

### Solo Developer / Learning
→ **Render (Free) or Railway ($5)**
- Easy to deploy
- No credit card required for free tier
- Perfect for learning

### Small Team / Startup
→ **DigitalOcean ($5-15) or Railway**
- Good balance of price and features
- Reliable infrastructure
- Room to grow

### Production / Enterprise
→ **AWS EC2 with Docker or AWS Lambda**
- Maximum control
- Auto-scaling
- Advanced monitoring

### Quick Demo / Prototype
→ **Vercel**
- Instant deployment
- Custom domain included
- Perfect for showing investors/users

---

## Post-Deployment Checklist

### Monitoring
- [ ] Set up error tracking (Sentry, DataDog)
- [ ] Enable logs in cloud platform
- [ ] Monitor API response times
- [ ] Track token usage (OpenAI, Anthropic)

### Security
- [ ] Add API key authentication
- [ ] Enable CORS restrictions
- [ ] Set up rate limiting
- [ ] Use HTTPS everywhere
- [ ] Rotate API keys regularly

### Performance
- [ ] Set up CDN for static files
- [ ] Cache embedding results
- [ ] Monitor cold start times
- [ ] Load test with k6 or locust

### Operations
- [ ] Set up health checks
- [ ] Create alerting rules
- [ ] Document deployment process
- [ ] Plan backup strategy

### Analytics
- [ ] Track query volume
- [ ] Monitor error rates
- [ ] Analyze query patterns
- [ ] Measure response times

---

## Quick Deploy Commands

### Docker (Local Testing)
```bash
docker build -t form-adv-rag .
docker run -p 5000:5000 \
  -e OPENAI_API_KEY=sk-xxx \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  form-adv-rag
# Visit http://localhost:5000
```

### Vercel
```bash
npm i -g vercel
vercel --prod
# Follow prompts, add env vars in dashboard
```

### Railway
```bash
# Just push to GitHub, Railway deploys automatically
git push origin main
```

### EC2 with Docker
```bash
# SSH to instance
ssh -i key.pem ec2-user@instance

# Install Docker and run
sudo yum install docker
sudo docker run -d -p 80:5000 \
  -e OPENAI_API_KEY=sk-xxx \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  form-adv-rag
```

---

## Troubleshooting Deployments

### "Import Error: No module named 'flask'"
- Check `requirements.txt` includes flask
- Run `pip install -r requirements.txt` before deploying

### "Vector store not found"
- Ensure `Data/chroma_openai/` is included in deployment
- Some serverless platforms don't persist files
- Use S3 to store and load vector store

### "API keys not working"
- Verify env vars are set in cloud platform
- Check `.env` not committed to git (add to `.gitignore`)
- Use separate keys for staging/production

### "Response too slow"
- Vector store might be large for serverless
- Consider upgrading instance size
- Add caching layer (Redis)

### "Out of memory"
- Reduce model size or use quantization
- Split into multiple containers
- Use serverless platform with larger memory

---

## Cost Optimization Tips

1. **Reuse Embeddings**
   - Cache OpenAI embeddings in Redis
   - Reduces embedding costs by 80%

2. **Batch Queries**
   - Combine multiple questions in one request
   - Better API rate limit utilization

3. **Compress Vector Store**
   - Use smaller embedding model if accuracy allows
   - Reduce storage and memory

4. **Monitor Usage**
   - Set up billing alerts
   - Review token consumption monthly

5. **Free Tier Maximization**
   - Use free tiers where available
   - Render + Railway for low-traffic
   - AWS free tier for learning

---

**Choose your platform above and follow the deployment steps. You'll have a live, production-ready RAG system in minutes.**
