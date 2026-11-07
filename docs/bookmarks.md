# Bookmarks

Searches the bookmarks of Chrome, Edge, Brave and Firefox. Type `bm github` or
`bookmarks github`; the keyword alone lists the most recently used ones. A bookmark
opens in your default browser, whichever browser it was saved in.

Each row shows the site's icon, a chip with where the link leads, such as
`github.com/bjspi/…`, and where the bookmark is saved: browser, profile and folders.

## Choose your profiles first

Nothing is listed until you choose it: turn on the profiles you want under Settings →
Plugins → Bookmarks, or add a custom path.

## Only behind a keyword

WinLauncher shows every plugin's items in ordinary searches at first, and a plugin
cannot change that. To keep your bookmarks out of them, turn off **In every search**
once under Settings → Plugins → Bookmarks. The keywords keep working.

## Where bookmarks come from

| Browser | Standard folder | File |
| --- | --- | --- |
| Chrome | `%LOCALAPPDATA%\Google\Chrome\User Data\<profile>` | `Bookmarks`, `AccountBookmarks` |
| Edge | `%LOCALAPPDATA%\Microsoft\Edge\User Data\<profile>` | `Bookmarks`, `AccountBookmarks` |
| Brave | `%LOCALAPPDATA%\BraveSoftware\Brave-Browser\User Data\<profile>` | `Bookmarks`, `AccountBookmarks` |
| Firefox | `%APPDATA%\Mozilla\Firefox\Profiles\<profile>`, or inside the package of the Microsoft Store version | `places.sqlite` |

- **Chrome, Edge and Brave** keep plain JSON. A signed-in profile may have only
  `AccountBookmarks`, so both files are read. The `Encrypted*` files beside them hold
  the same bookmarks and cannot be read.
- **Firefox** keeps an SQLite database. So that Firefox's locks cannot get in the way
  and the plugin takes no part in them, it never opens that database: it copies it and
  its write-ahead log into its data folder, reads the copy and deletes it. The copy
  holds your browsing history for that moment, because the history is in the same file.
  A copy left behind by a crash is deleted by a later refresh.
- **HTML files** exist only when you export your bookmarks. Browsers do not keep any
  by themselves, but you can name an exported file as a custom path.

A browser counts as present when it left a profile with bookmarks in these folders,
so a browser you uninstalled may still offer its profile.

## Icons

The icons come from the cache each browser keeps of the sites it showed: `Favicons`
in a Chromium profile, `favicons.sqlite` in a Firefox profile. No site is contacted.
A bookmark the browser holds no icon for gets the icon of another page of the same
site, else the plugin's own. The caches are read through a private copy, like
Firefox's bookmarks, and only the icons of your bookmarks are kept, as image files in
the plugin's data folder; icons no bookmark uses any more are deleted. A cache that
cannot be read leaves the bookmarks listed without icons.

## Settings

- **Bookmarks:** the most to list, at most 5,000, most recently used first. The same
  address saved in several browsers or profiles is one row.
- **Excluded bookmarks:** one [fnmatch](https://docs.python.org/3/library/fnmatch.html)
  pattern per line, ignoring case: `*`, `?`, `[abc]` and `[!abc]`. A line hides a
  bookmark when it fits the whole title, the whole address or the whole name of a
  folder the bookmark lies in, at any depth. So `bank` hides only a title that is
  exactly "Bank"; use `*bank*` for any title containing it:

  ```text
  *banking*
  https://intranet.example/*
  Private
  ```

- **Custom paths:** one per line, for portable browsers and others such as Vivaldi or
  Chrome Beta. These are always read. Environment variables work. A line may name:
  - a profile folder (holding `places.sqlite` or `Bookmarks`);
  - a Chromium `User Data` folder or a Firefox folder with `profiles.ini`, to read
    all of its profiles;
  - a file: `.html` is read as an export, `.sqlite` as a Firefox database, and
    anything else as a Chromium bookmark file.
- **One switch per profile:** all are off at first. The switches list what was found
  when WinLauncher started; a newer profile gets its switch at the next start.

**Show sources** lists what was recognized, how many bookmarks and icons each source holds and
what could not be read.

## Limits

Only `http`, `https` and `ftp` addresses are listed. Bookmarklets and browser pages
such as `chrome://settings` cannot be opened from outside a browser. Other schemes are
left out because Windows could start a program for them: a `file:` address may name a
program, even on a network share, and would run instead of opening in your browser.

A path that cannot be read is written to the log and listed by **Show sources**,
while the other browsers keep working. The refresh only fails when nothing at all
could be read.
