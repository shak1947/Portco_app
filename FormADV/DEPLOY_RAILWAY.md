# Deploy Form ADV RAG to Railway - Step by Step

**Time Required:** 5 minutes
**Cost:** Free tier or $5/month
**Result:** Public link you can share

---

## Step 1: Go to Railway.app

1. Visit https://railway.app
2. Click **"Start New Project"** (top right)
3. Click **"Deploy from GitHub"**

---

## Step 2: Connect GitHub

1. Authorize Railway to access GitHub
2. Select repository: **shak1947/Portco_app**
3. Select branch: **db-only** (where we just pushed the code)
4. Click **"Deploy"**

Railway will automatically detect it's a Python project and start building.

---

## Step 3: Wait for Build (2-3 minutes)

You'll see:
```
✓ Building Python project...
✓ Installing dependencies...
✓ Starting application...
✓ Deployment complete!
```

---

## Step 4: Set Environment Variables

Once deployed:

1. Click on the **"Variables"** tab
2. Add two environment variables:
   - **Name:** `OPENAI_API_KEY`
   - **Value:** `YOUR_OPENAI_API_KEY_HERE`

3. Click **"Add Variable"** again for the second one:
   - **Name:** `ANTHROPIC_API_KEY`
   - **Value:** `YOUR_ANTHROPIC_API_KEY_HERE`

4. Click **"Deploy"** button (it will redeploy with new env vars)

---

## Step 5: Get Your Public URL

1. Go to the **"Settings"** tab
2. Under "Domains", you'll see a public URL like:
   ```
   https://form-adv-rag-production-xxxx.railway.app
   ```

3. **Click the domain** to visit your live system!

---

## Step 6: Test It Out

Your system is now **live and public**! 

Try these:
- Visit `https://your-domain.railway.app/` → See the UI
- Visit `https://your-domain.railway.app/api/health` → Check status
- Visit `https://your-domain.railway.app/api/firms` → See available firms

---

## Step 7: Share the Link

You now have a public URL to share:
```
https://form-adv-rag-production-xxxx.railway.app
```

**Share this with:**
- Interviewers (as a portfolio demo)
- Friends (show off the system)
- Investors (if pitching)
- Resume/LinkedIn (with link to live demo)

---

## How to Update After Deployment

If you make changes:
```bash
# Make changes locally
git add .
git commit -m "Update..."
git push origin db-only
```

Railway automatically redeploys when you push! ✅

---

## Troubleshooting

### "Build failed"
- Check that `requirements.txt` is in root directory
- Check `Procfile` exists with: `web: python app.py`
- Look at build logs for error details

### "Application won't start"
- Check environment variables are set
- Look at runtime logs in Railway dashboard
- Verify `app.py` has `host="0.0.0.0"` in the run command

### "Endpoint returns 500 error"
- Check API keys are correct in environment variables
- View logs in Railway dashboard
- Common cause: Wrong API key format

### "Page loads but queries don't work"
- Click `/api/health` to verify backend is running
- Check that API keys are set in environment variables
- Look at runtime logs for errors

### "How do I view logs?"
- In Railway dashboard, click **"Logs"** tab
- Scroll to see what your app is doing
- This helps debug issues

---

## Cost

**First month:** FREE (Railway gives $5 credits)
**After that:** 
- Free tier: Runs 500 hours/month (plenty for demo)
- Paid tier: $5/month minimum

---

## What Just Happened

You deployed a **production-ready AI system** to the internet! 🚀

Architecture:
```
Your Browser
    ↓
Railway (running Flask)
    ↓
OpenAI API (embeddings)
Chroma Vector Store (local file, 428MB)
Claude API (synthesis)
    ↓
Your Browser gets answer with citations
```

Everything runs in Railway's containers. The 428MB vector store is included in the deployment. API keys are kept private in environment variables.

---

## Next Steps

1. **Test the live system**
   - Ask questions on the public URL
   - Share with friends
   - Get feedback

2. **Add to your portfolio**
   - Update resume with live link
   - Add to GitHub profile
   - Tweet about it

3. **Show in interviews**
   - "Here's the system I built and deployed"
   - Shows full-stack + deployment skills
   - Can demo live to interviewers

4. **Optionally improve**
   - Add more documents
   - Add authentication
   - Add analytics
   - Set custom domain

---

## Success! 🎉

Your Form ADV RAG system is now live and shareable.

**Public URL:** https://form-adv-rag-production-xxxx.railway.app

**What you've demonstrated:**
✅ Full-stack AI system building
✅ Production deployment
✅ Public-facing application
✅ Interview-ready project

---

**Any issues? Check the Railway docs at https://docs.railway.app**
