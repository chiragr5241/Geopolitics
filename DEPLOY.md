# Deploy to GitHub & GitHub Pages

## 1. Create GitHub Repository

1. Go to [github.com/new](https://github.com/new)
2. Repository name: `geopolitics` (or `global-operations-map`)
3. Description: `Interactive OSINT map of global military operations 2023-2026`
4. Choose **Public**
5. **Do NOT** initialize with README (we already have one)
6. Click **Create repository**

## 2. Push Code

Run these commands (replace `YOUR_USERNAME` with your GitHub username):

```bash
cd /Users/chiragrastogi/Dev/research/geopolitics

# Rename branch to main (GitHub default)
git branch -M main

# Add your GitHub repo as remote
git remote add origin https://github.com/YOUR_USERNAME/geopolitics.git

# Push
git push -u origin main
```

## 3. Enable GitHub Pages

1. In your repo: **Settings** → **Pages**
2. Under **Source**: select **Deploy from a branch**
3. **Branch**: `main` / **Folder**: `/ (root)`
4. Click **Save**
5. Your site will be live at: `https://YOUR_USERNAME.github.io/geopolitics/`

## Security Checklist ✓

- [x] No API keys or credentials in code
- [x] Data marked OPEN SOURCE / UNCLASSIFIED
- [x] All imagery from Wikimedia Commons (public domain)
- [x] `.claude/` excluded via .gitignore
