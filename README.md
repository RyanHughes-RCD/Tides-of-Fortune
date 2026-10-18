# Tides of Fortune: home-screen app

These files are the whole game. Put them on GitHub Pages and anyone can open it in a browser, add it to their home screen, and play it offline.

## What's in this folder

| File | What it does |
|---|---|
| `index.html` | The game |
| `sw.js` | Keeps the game on the phone so it works offline |
| `manifest.webmanifest` | The app's name, icon and full-screen setting |
| `icon-180.png`, `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` | App icons |
| `README.md` | This guide |

All the files sit side by side. There are no folders to recreate.

## 1. Create the repository

1. Sign in at github.com.
2. Tap **+** (top right), then **New repository**.
3. Name it `tides-of-fortune`.
4. Choose **Public**. GitHub Pages is free for public repositories; private ones need a paid plan.
5. Tap **Create repository**.

## 2. Upload the files

**On a computer:** unzip `tides-of-fortune.zip`, open the repository page, choose **Add file → Upload files**, drag in all the files from the folder, then tap **Commit changes**.

**On an iPhone:**
1. In the Files app, tap the zip to unzip it.
2. In Safari, open your repository page, tap **aA** in the address bar, then **Request Desktop Website** (the phone layout hides the upload button).
3. Choose **Add file → Upload files → choose your files**, select every file inside the unzipped folder, then tap **Commit changes**.

## 3. Turn on GitHub Pages

1. In the repository, open **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
3. Set the branch to **main** and the folder to **/ (root)**, then tap **Save**.
4. Wait a minute or two, then refresh. The page shows your link:
   `https://YOUR-USERNAME.github.io/tides-of-fortune/`

## 4. Install it on your iPhone

1. Open the link in **Safari** (other browsers on iPhone can't install apps).
2. Wait for the harbor to appear. That first visit saves the game for offline play.
3. Tap **Share**, then **Add to Home Screen**, then **Add**.
4. Open Tides from your home screen. It runs full screen and works in airplane mode.

On Android, open the link in Chrome and choose **Install app** or **Add to Home screen** from the menu.

## 5. Bring over your harbor from claude.ai

1. In the claude.ai version: **Options → Save backup → Copy save code**.
2. In the installed app: **Options → Save backup**, paste into **Load a save**, then tap **Load this save** twice.

Ships at sea keep sailing; timers carry over.

## 6. Share with friends

Send them your link. They follow step 4 on their own phones. Each person gets their own harbor, saved on their own phone.

## 7. Installing an update

When you get a new version of the game, upload the new files to the same repository (they replace the old ones) and commit. The next time the app opens with a connection, a **New version ready: tap to restart** button appears near the top. Tap it; your save stays.

## Good to know

- **Sound:** on an iPhone, the ring/silent switch must be on ring.
- **Saves live on the phone.** Deleting the app from the home screen, or clearing Safari's website data, deletes the save. Use **Copy save code** now and then and keep it in Notes.
- **Private browsing** doesn't keep saves.
- **Live weather** works in the installed app. In **Options → Sky and weather**, tap **Use my location** (or type a town) to follow your real weather.

## Troubleshooting

- **The link shows a 404 page:** Pages takes a few minutes the first time. Check that `index.html` is at the top level of the repository, not inside a folder.
- **Still showing an old version:** close the app completely and open it again (twice if needed), or tap the update button when it appears.
- **No Add to Home Screen option:** make sure you're in Safari, not Chrome or a link preview inside another app.
