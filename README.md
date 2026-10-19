# Tides of Fortune: home-screen app

**Version 1.5.3.** These files are the whole game. Put them on GitHub Pages and anyone can open it in a browser, add it to their home screen, and play it offline.

## What's in this folder

| File | What it does |
|---|---|
| `index.html` | The game |
| `sw.js` | Keeps the game on the phone so it works offline |
| `manifest.webmanifest` | The app's name, icon and full-screen setting |
| `icon-180.png`, `icon-192.png`, `icon-512.png`, `icon-maskable-512.png` | App icons |
| `README.md` | This guide |
| `Pixeloid-font-license.txt` | License for the Pixeloid font used in the game |

All 9 files sit side by side. There are no folders to recreate.

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

## What's new in 1.5.3

- The Sea Witch's roof now rises out of the hut in one smooth, gradual taper before curling over at the top, instead of a thin spike sitting on the roof.

## What's new in 1.5.2

- The West Woods cauldron is bigger and more detailed: a stone fire pit with crackling logs, a shaded iron pot on three legs, a swirling brew with bubbles that rise and pop, steam, a stirring paddle, candles, potion jars, mushrooms and pumpkins. Its patch of dirt now fades into the grass instead of sitting as a brown circle.
- The Sea Witch's hut stands on stilts with a ladder, under a curled witch-hat roof tipped with a gold star. It has a moon window and drying herbs, mushrooms and a bubbling pot in the yard, a broom from level 2, and a black cat on the roof at level 3.

## What's new in 1.5.1

- Friendly Halloween ghosts now drift through the village in the daytime too (a little less often than at night).
- You can build a few tiles further out to the west, into the edge of the woods, and to the east, past the field. The starting village is unchanged, and the West Woods cauldron moved a little deeper into the trees to make room.

## What's new in 1.5: more ships and steadier screens

- **Three new mid-tier ships** fill the gap between the trawler and the galleon. Each is an all-rounder rather than the best at one job:
  - **Revenue Cutter (tier 2):** fast and armed, the first ship that can hunt pirates, and decent at treasure and exploring.
  - **Survey Ketch (tier 3):** an explorer that also hunts treasure well.
  - **Corsair Xebec (tier 4):** a quick raider that fights, scouts and loots.
- **Rebalanced fleet:** the Fishing Skiff now fishes at 8 (was 9), the Fishing Trawler at 13 (was 14), and the Arcane Frigate is now the best treasure hunter. Ships already at sea finish their trip with the stats they sailed with.
- **Collecting from many ships** now scrolls the reward list, and the button always stays on screen.
- **Shipwright → Upgrades:** the ship strip no longer jumps back to the start while you scroll.
- Each ship card now says what it's good at, based on its real strengths.

## What's new in 1.4: a bigger village to make your own

- **More land.** The map grew from 40×40 to 48×48 tiles, with a wide new peninsula to the south and roads into it. Everything you've already built stays exactly where it was.
- **The lighthouse island** now stands much further out to sea.
- **Lighter fog.** Foggy weather is about half as thick.
- **Two new top-tier ships** (they need a level 3 Dockyard):
  - **Leviathan Trawler:** the best fishing ship, with a 420-unit hold.
  - **Star Clipper:** the fastest hull and the best explorer.
- **Ten new decorations** to fill the extra space. Village buildings: Seaside Cottage, Windmill (sails turn), Bell Tower, Fisher's Hut, Gazebo. Village square: Market Stall, Topiary Hedge, Duck Pond, Founder's Statue, Village Well. Each gives a small bonus once, but you can build up to 12 of each to shape your village. Most come in several colours or styles: tap one in the village and press **Repaint** (free).
- **More candy from trips, less from ghosts.** Trips find candy more often and in bigger handfuls (about 1.6 candy per hour at sea, up from 0.9). Ghosts now give 1–2 candy, up to 4 times an hour.

## What's new in 1.3: Halloween, refining for profit, and a cleaner harbor view

**Halloween event (October 1 to November 12, every year).** It starts and stops by itself using the phone's date. No new game needed.

- **Candy:** every trip, of every type and length (even 15 minutes), can bring home candy. Tap the candy counter at the top to open the Halloween panel.
- **The West Woods cauldron:** pan left past the village to the forest clearing, or use **Show me the cauldron**. Deposit candy for a random prize:

  | Wager | Candy | Common | Uncommon | Rare | Very rare |
  |---|---|---|---|---|---|
  | Small handful | 12 | 62% | 28% | 8.5% | 1.5% |
  | Generous handful | 30 | 38% | 36% | 20% | 6% |
  | Big cauldron dump | 60 | 16% | 30% | 32% | 22% |

  Prizes are mostly the 12 Halloween decorations, plus chest keys, coins and bundles of goods (bigger wagers multiply coin and goods prizes). Every draw gives something. Candy is taken and the prize given in one step, so closing the app mid-brew loses nothing; the reveal shows the next time you open it.
- **12 Halloween decorations** (won, never bought; duplicates welcome): Pumpkin Flag, Classic Jack-o'-Lantern and Crooked Tombstone (common); Ghost Flag, Silly Jack-o'-Lantern, Haunted Scarecrow and Eerie Lantern (uncommon); Witch Flag, Waving Skeleton and Bat Roost (rare); Spooky Jack-o'-Lantern and Miniature Cauldron (very rare). Each placed one adds +4% to +10% candy from trips (all jack-o'-lanterns +6%). Copies stack up to +50% in total. Tap a placed one to move it or pack it away.
- **Friendly ghosts** float through the village at night. Tap one to pop it for 1 to 3 candy (1.4: 1 to 2 candy, up to 4 paid pops an hour).
- **The ghost ship** drifts into the north harbor every 5 to 10 hours for about 25 minutes. Tap it to trade candy for timber, stone (iron ore), food, mixed crates and sometimes a big cargo. Each offer can be taken once.
- **Village dressing:** some buildings get cobwebs, bats, pumpkins, tombstones and coloured lights while the event runs. It is only an overlay, so nothing blocks doors or paths, and it all disappears after the event.
- **After November 12:** no more candy, ghosts or ghost ship, and the cauldron goes cold. Your candy and decorations stay for next year.

**Refining for income**
- Planks, rope and iron now sell for exactly **12 coins each**, at the Stores (no Trading Post needed) or at a Trading Post. Raw goods, food and the catch keep their old prices.
- Batches are bigger: up to 25 per building level (25, 50, 75). Choose **1, 5, 10 or Max**. The card shows the batch's time and its value (units × 12 coins), and a batch never exceeds your storage room. Timers and input costs are unchanged.

**Ships button:** the list of voyages on the main screen is replaced by one **Ships** button (it turns gold and says **Ready!** when a ship is back). It opens the Fleet view: every ship, with its status, trip type and time left.

Saves from 1.2 load straight into 1.3. In **Options → Developer mode** you can force the event on or off to try it out.

## What's new in 1.2: decorations and village expansion

- **Decorations** (Village → Decorations tab). Each one is placed instantly, needs no builders and gives a small, lasting bonus. You can own one of each, and the combined bonus is capped, so decorating helps without replacing the work of growing the village.

  | Decoration | Bonus |
  |---|---|
  | Scarecrow (in the field) | The field ripens 10% faster |
  | Field fence (round the field) | +2 food every harvest |
  | Kitchen garden | +3 food every harvest |
  | Barrels and boxes | +50 storage for each bulk good |
  | Crab statue (on the shore) | +5% fishing hauls |
  | Harbor lantern | Every trip is 3% shorter |
  | Festival lanterns | Builders finish 5% faster |
  | Keeper's shack (beside the lighthouse) | 5% less hull damage |
  | Lily of the valley bed | +3% treasure-hunting hauls |
  | Sunflower bed | +3% exploration power |
  | Rose bed | +3% pirate-hunting power |
  | Tulip bed | +3% fishing hauls |
  | Fountain (freezes over in snow) | Treasure chests turn up 10% more often |
  | Chest of gold (prestige) | +5% coins from every trip |

- **Lighthouse island** is bigger, with room for the keeper's shack, and turns snowy along with the village.
- **Bigger harbor view.** The land and sea now carry on past the edges of the village, so the screen is always full and you can pan the village right to the top and bottom of the screen.
- **Ships at the jetties** now bob behind the planks instead of drawing over them.
- The version number is shown at the bottom of **Options**.

## Good to know

- **Sound:** on an iPhone, the ring/silent switch must be on ring.
- **Saves live on the phone.** Deleting the app from the home screen, or clearing Safari's website data, deletes the save. Use **Copy save code** now and then and keep it in Notes.
- **Private browsing** doesn't keep saves.
- **Live weather** works in the installed app. In **Options → Sky and weather**, tap **Use my location** (or type a town) to follow your real weather.

## Troubleshooting

- **The link shows a 404 page:** Pages takes a few minutes the first time. Check that `index.html` is at the top level of the repository, not inside a folder.
- **Still showing an old version:** close the app completely and open it again (twice if needed), or tap the update button when it appears.
- **No Add to Home Screen option:** make sure you're in Safari, not Chrome or a link preview inside another app.
