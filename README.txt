Sluka Desktop 0.16.2 for Windows
================================

Sluka, the language-learning browser extension, as a program of its own:
its dashboard, books, videos and audio in windows of their own, its
subtitles and word cards inside mpv, its words in Anki's review screen,
and its subtitle box floating over any other program -- with the text of
the game you are playing in it.
It is the app made for Tails, with Windows' ways in place of Linux's.

New in 0.16.2:

- "Sync with this device", and Import in "Import words and progress",
  with a large backup -- many words, or long Anki and reading histories
  -- no longer stop at "Could not restore: Sluka Desktop's host did not
  answer (storage): Failed to fetch".  Sluka writes such a backup into
  its store in one go, of more than 8 MB, and the app answered that
  without reading it; it reads it whole now, as any smaller one.
- Everything else is as in 0.16.1 (the add-on only says 0.16.2).

New in 0.16.1:

- Syncing through Google Drive, or any folder kept in step (OneDrive,
  Dropbox, Syncthing, a USB stick), now works as in Chrome: Settings →
  Sync & backup → "Choose a folder" opens Windows' own folder window, and
  the folder chosen -- G:\My Drive\Sluka, say -- stays Sluka's after the
  app is closed and started again.  Sluka writes this computer's backup
  there by itself every few minutes and reads the other devices' from it,
  and the steps of "Sync through Google Drive" can be followed as they
  are written.  Before, the app had no folder to offer: it wrote its
  backup only into data\Downloads\Sluka, about once a day, where no other
  device could see it, the Google Drive steps' "Choose the folder" failed,
  and the other devices' backups came in only by "Read from a folder…",
  picked anew each time.  A backup set up that old way keeps going until
  "Choose a folder instead" is pressed (section 3).
- Everything else is as in 0.16.0 (the add-on only says 0.16.1).

New in 0.16.0:

- Your own dictionaries in the word panel of the floating subtitles, of
  Sluka Vision and of mpv: the ones added in Settings → Dictionary →
  "Your own dictionaries" (Yomitan dictionaries and tables), drawn as
  the extension's own panel draws them, each under its name -- instead
  of Sluka's meanings, under them or above them, as Settings says there
  (section 5).
- More kinds of dictionary for that card, for learners of every
  language: in the app, its "Add a dictionary…" also takes StarDict
  dictionaries (GoldenDict's), ABBYY Lingvo's .dsl files, JMdict,
  CC-CEDICT, CC-Canto, Folkets lexikon and kaikki.org's Wiktionary
  files -- plain, gzipped, or in a .zip or a .tar -- each made into a
  Yomitan dictionary on this computer first, then added by the
  extension as any of its own (section 5).
- The AI check's ✦ in the word panel, as in the extension's: where the
  dictionary has the word, a key in the head; where nothing has it, a
  button in the meanings.  Pressed, or F (Settings → Keyboard), it sends
  the word and its sentence to the AI that Settings → AI check sets up,
  and your own request there (Advanced → "Your own request": what the
  word means here, how its sentence changes it, ...) is answered under
  "Your question" -- with nothing to type.  It is there only where
  Settings → AI check is on (section 5).
- Sluka Vision's Alt+P or Alt+F pressed again and again quickly: the
  last press decides, whatever order the screen reader's answers come
  in (before, one could be lost, and the game left the other way).  The
  same key again before the picture has come lets it go, as it does
  once it has.
- Everything else is as in 0.15.0 (the add-on only says 0.16.0).

New in 0.15.0:

- Sluka Vision stops the game where it is, to read it at leisure -- two
  ways, each with its own key, for each game the one that suits it
  (section 7, Sluka Vision).  Alt+P pauses the game itself: its picture,
  its sound, its cutscene and its timers stop, and its picture, taken
  the moment before, is laid over its window with the words on it.
  Alt+F only freezes the picture: the game goes on behind it, for a game
  that should not be paused.  Either key again lets go; the other key
  while one is on switches to it, the picture kept as it is.
- Everything else is as in 0.14.2 (the add-on only says 0.15.0).

New in 0.14.2:

- The word panel of the floating subtitles, of Sluka Vision and of mpv
  has the extension's speaker, in the head's top left corner with the
  word beside it: a click (or V, Settings → Keyboard) says the word, and
  it is lit while it is said.  The voices are the extension's, in the
  order Settings → Voice puts them -- your cloud voice, your own Piper
  voice, the recordings where you have installed them -- and where no
  cloud voice is set up, Google Translate's voice stands in for one:
  every language Sluka has can be heard, online, with nothing to
  download (the extension's own translation box speaks with the same
  voice).  A cloud voice that fails (its quota, say) has Google's answer
  before the computer's own voice.  Settings → Voice → "Say a word when
  you open it" says it on the click, as on a page (in mpv, while the
  video is paused).
- Everything else is as in 0.14.1 (the add-on only says 0.14.2).

New in 0.14.1:

- Every window of Sluka's has a black title bar, as Setup's has, whatever
  Windows' own colours (before, only with Windows set to dark mode).
- Everything else is as in 0.14.0 (the add-on only says 0.14.1).

New in 0.14.0:

- The word panel of the floating subtitles, of Sluka Vision and of mpv
  has the head's keys of the extension's own panel, with its marks, left
  of the cross: Translate, Look up and Anki (moved there from beside the
  cross, where 0.13.0 put it alone).
- Translate: the word put into Google Translate, as the extension's
  Translate key puts it, and its translation shown in the panel, under
  the word (without the box for a meaning of your own).
- Look up: the menu of your dictionary sites for the language, as
  Settings lists them, each opened in a small window of Sluka's own --
  not your browser, and with web data of its own, apart from the app's.
  Beside a site whose dictionary its makers publish for anyone to use,
  the same dictionary offline: Wiktionary (every language), JMdict
  (Jisho's, Japanese), CC-CEDICT (MDBG's, Chinese), CC-Canto (Cantonese)
  and Folkets lexikon (Swedish).  Its first click offers to install
  it -- how large it is, then downloaded from its makers' own site --
  and from then on it is read offline, in a small window of its own
  (section 5).
- Everything else is as in 0.13.0 (the add-on only says 0.14.0).

New in 0.13.0:

- Anki cards from games and films: the word panel of the floating
  subtitles, of Sluka Vision and of mpv has Sluka's Anki key, as a page's
  panel has it -- a click on it, or its key (Settings → Keys, P unless set
  otherwise), adds the word to Anki with the sentence it stands in, and
  once it is there opens its card in Anki.  The card is the extension's
  own, made as Settings → Anki says: your note type, your decks, and what
  its Media settings put on it.
- From a game (the floating subtitles with the game hooked, or Sluka
  Vision): the line's sound and a picture of the game.  While the game is
  hooked, or its window is the one Sluka Vision reads, Sluka keeps the
  last minute of that game's own sound -- that program's alone, not your
  music or a call (Windows 10 version 2004 or later) -- in memory only, and
  a word's clip is cut from it: from a little before its line came to
  where its voice stops, or where the next line came.  "With the sentence
  before and after" takes the lines either side into the sentence and the
  clip.  Where the video is chosen, a game's card gets the picture
  instead, as the extension does where a video cannot be made.
- From mpv: the subtitle line's sound, read out of the file itself as
  Sluka's videos page reads a video file of yours, and the frame on
  screen -- and the video itself, where it is chosen.
- A word graded in mpv, the floating subtitles or Sluka Vision is told to
  Anki as a grade on a page is: where Settings → Anki sends words by
  themselves, with the sentence it was graded in.
- Everything else is as in 0.12.5 (the add-on only says 0.13.0).

New in 0.12.5:

- Sluka Vision, and the Screen tab, reading the game's own window ("What
  is read", for Sluka in your screenshots and recordings): a game whose
  window kept giving Sluka an old picture -- Ace Attorney, its title
  menu, however often it was read again -- is read as it is.  Such a
  window is now taken as Windows itself draws it, wherever the quicker
  way gives a picture that is not what the game shows: Sluka's words
  still show in screenshots and recordings.  Where even Windows' own
  picture of it stands still while the game goes on, Sluka reads what
  the screen shows there instead, and says so in a message of its own,
  once a game: Sluka needs that to read the game right, and its words
  are then left out of screenshots and recordings of that game (section
  7).
- Setup's window and its text are a quarter larger, for reading ease
  (less, on a screen too small for that).
- The licence agreement, LICENSE.txt, is shorter: Sluka's terms; a
  paragraph of credit to those whose software Sluka Desktop stands on;
  no warranty; and the law -- Swedish, as for the Sluka extension, a
  consumer keeping the mandatory rules of the country where they live,
  with Allmänna reklamationsnämnden (ARN) for disputes.  The rest --
  what Sluka Desktop does and sends, its free parts, Microsoft's terms
  for its runtime files, and file by file whose software is in it -- is
  in NOTICES.txt (the third-party notices of 0.12.4, under a new name),
  which Setup shows after the agreement (section 15).
- Everything else is as in 0.12.4 (the add-on only says 0.12.5).

New in 0.12.4:

- Setup is black, in Sluka's own dark colours: its title bar, its pages,
  and its buttons and boxes, with Sluka's blue on the main button and on
  what is ticked.
- Setup's first page is the licence agreement (LICENSE.txt): read it, and
  tick "I accept the licence agreement" to go on -- for an update too.
  Sluka Desktop is used under Sluka's terms (sluka.app/terms); the parts
  that are free software say so, and the software of others in it is
  listed, with its licence and where its source code is, in the notices
  beside it (NOTICES.txt, from 0.12.5) and the LICENSES folder.  "Licences
  and notices", in each window's menu, opens the agreement; section 15
  says more.
- Google Lens asks first: before Sluka Vision (or the Screen tab, where
  it is set to Google Lens) sends Google its first picture, a message
  box says what goes where, and asks.  Yes: Google Lens reads, and the
  question is not put again (About, in the window menu, can have it put
  again).  No: an offline reader reads instead -- Sluka's own OCR for
  Sluka Vision -- and is chosen in its place.  Until the answer, the
  offline reader reads: nothing goes to Google before a yes.
- The Snipping Tool's OCR is no longer one of the readers: it was copied
  out of Windows 11's Snipping Tool app, which Microsoft has not licensed
  for other programs to do.  Where it was chosen, the Screen tab reads
  with "Auto" and Sluka Vision with Sluka's own OCR, and the copies that
  earlier versions made (data\ocr\SnippingTool) are taken away.
- Sluka's own OCR turns off the trace events that Microsoft's ONNX
  Runtime keeps for Microsoft (through Windows' diagnostic data).
- A font whose own licence forbids changed copies -- the fonts Microsoft
  supplies with Windows -- is no longer copied for mpv at another weight
  (section 4): mpv draws it as it is.  Noto's, among them those Windows 11
  brings for Japanese, are copied as before.
- Setup in a terminal (--headless) installs and updates only with
  --accept-license, once its agreement has been read with
  --headless license.
- Everything else is as in 0.12.3 (the add-on only says 0.12.4).

New in 0.12.3:

- What you read and hear with the desktop's tools now counts on Sluka's
  Home page -- Today's Reading and Listening, and the days, goals and
  streaks behind them -- by the rules Sluka's own pages count by:
  - mpv: Listening, as Sluka's Your videos page counts a film: while it
    plays with its sound on, never more than the real time that passed,
    and only for a film Sluka can tell is in a language you learn -- its
    audio or subtitle track is marked with one, or its subtitles or its
    title are written in one (until something says so, its time is held,
    and counted once something does).  Each film gets its row in the
    Listening tab (Progress > Listening), as a "Local video".  A subtitle
    line half of which has played counts as subtitle words, as SlukaCC
    counts one; those go into Reading where Settings > Reading > "Words in
    subtitles count as words read" is on.  Two films playing at once count
    once.
  - The floating subtitles (the Game, Screen and Clipboard tabs, and text
    other programs send) and Sluka Vision: Reading, as a page's words are
    counted -- at your own pace, for as long as the text is up and you are
    there, never more than its own words, and a line seen again on the
    same day once.  Your pace is learned from how fast you go through the
    lines (apart from your pace on pages, which is left as it was); until
    then it starts on the low side, as on pages.  Only words in the
    language's own writing count: an English menu over a Japanese game is
    no Japanese read.  With Settings > Reading > "Count words read" set to
    Sluka's own reader and books, none of it counts.
  - A game -- the Game or Screen tab, or Sluka Vision, reading it: half of
    the time it is played counts as Listening, a game's sound being voices
    and music both.  Played is: the game is the window in front (the
    floating subtitles or Sluka Vision's words over it change nothing),
    you pressed a key, used the mouse or a game controller, or the game
    gave new text, in the last five minutes, and its text is in a language
    you learn (some of it was read in the last half hour).  The Clipboard
    tab counts as Reading only: what is copied can come from any program.
- mpv: the script tells the app how far the film has played -- once a
  second while it plays, and at each pause, seek, end and change of sound.
  An mpv opened before the update counts nothing until it is opened again.
  The app's log has a line for each film: how many minutes counted, or why
  they did not (never the film's name).
- Everything else is as in 0.12.2 (the add-on only says 0.12.3).

New in 0.12.2:

- Sluka in your screenshots and recordings (OBS, the Snipping Tool,
  Discord), to share: choose "The game's own window" as what is read --
  in Sluka Vision settings ("What Sluka Vision reads"), and in the Screen
  tab's Reading settings ("What is read").  Sluka then reads the game's
  own picture, under its words, and no longer has to leave its windows out
  of pictures of the screen: Sluka Vision's words, cards and panels, the
  floating subtitles and the menu all show in them.  Where a game's own
  window cannot be read as it shows (it gives no picture of itself, or
  Windows enlarges it for a 125 % or 150 % screen), what the screen shows
  is read there instead, and Sluka's windows are left out of pictures for
  that game meanwhile -- the menu says so.  Read off the screen, as it
  comes, nothing changes: Sluka is left out of screenshots and recordings
  then, so that it never reads its own words back.  In the Game and
  Clipboard tabs, the floating subtitles were and are always in them.
- When a tab that reads the screen is left, every window of Sluka's that
  shows is put back in pictures of the screen, whatever was left out
  before.
- Everything else is as in 0.12.1 (the add-on only says 0.12.2).

New in 0.12.1:

- A word's own level in a panel, clicked again, puts the word back to New,
  as on Sluka's pages ("Back to new" on its button) -- in Sluka Vision and
  in the floating subtitles.  A double-click on a level does not undo
  itself.
- Sluka Vision: while a word's panel is open over the game, Sluka's own
  keys grade it -- 1 to 4, K known, X ignore, 0 back to New, as Sluka is
  set -- and Esc closes it.  The game has those keys back the moment the
  panel closes, or when another window (Sluka's own too) comes in front.
- Sluka Vision: text on a moving or glowing button keeps its words and its
  card.  A line's words now go once what changed under them has stood
  still a moment (the next line of dialogue still goes within half a
  second), not while it moves, nor where it keeps moving; they come back
  when what is under them is again as it was read (a button the pointer lit
  goes dark again).  The word pointed at keeps its card while the pointer
  is on it, and what changes under it alone -- a button lit by the pointer
  -- does not have the window read again under the card.
- The frozen white "Sluka Desktop" window that came up while switching tabs
  of the game text menu: the Screen and Sluka Vision tabs no longer touch
  Sluka's never-shown window (its background worker's) when they keep
  Sluka's windows out of pictures of the screen -- the one thing that
  touched it -- and if anything ever shows it again, it is hidden again at
  once (the log says so: "was found on the screen").  Its close button
  only hides it.
- 👀: a click on a word in Sluka Vision, the floating subtitles and mpv now
  counts as a lookup, as a click on Sluka's pages does (once a minute at
  most), into the same counts -- Anki's, the dashboard's "Most looked up".
  Sluka Vision's and the floating subtitles' panels show it from the third
  lookup, as Sluka's do.  (mpv's panel is as it was: its clicks are
  counted, the number is shown elsewhere.)
- Sluka Vision: the taskbar is never taken for the game (Alt+S pressed just
  as the game was gone back to read the taskbar).
- Everything else is as in 0.12.0 (the add-on only says 0.12.1).

New in 0.12.0:

- Sluka Vision, a new tab of the game text menu (section 7), in place of
  the Other program tab: the words of a game's whole window read off the
  screen and laid over the game where they sit, as YomiNinja does -- each
  word you are learning underlined in its level's colour (beside it, in a
  column of vertical text), its card when you point at it, its panel and
  its levels when you click it.  Nothing is written over the game's own
  letters.  Press Alt+S in the game (YomiNinja's key; change it in the
  tab): the window in front is read with Google Lens, tilted lines and
  columns included, furigana left out.  With "Read again by itself" on --
  as it comes -- the window is read again each time what it shows has
  changed and settled, and the words of what is gone are put away at
  once, so that none is left under the wrong text.  Alt+V puts the words
  away.  The floating subtitles rest meanwhile.
- The Other program tab is gone (Sluka Vision has its place): the
  Clipboard tab still takes the lines LunaTranslator or Textractor read
  (set them to copy each line).
- Everything else is as in 0.11.0: Setup, the Game, Screen and Clipboard
  tabs and their keys, the floating subtitles, mpv and Anki (the add-on
  only says 0.12.0).

New in 0.11.0:

- Sluka-Desktop-Setup-0.11.0.exe: a Windows setup like any other, in place
  of 0.10.0's setup in a black window.  Double-click it: Welcome, the
  folder (Browse...), tick boxes for a shortcut on the desktop and Sluka in
  the Start menu (and Sluka in Anki, where Anki is), your Sluka extension's
  zip (found in Downloads by itself), a progress bar, and "Start Sluka
  Desktop now".  Opened again -- from the Start menu ("Sluka Desktop
  Setup"), or Settings > Apps > Sluka Desktop -- it updates Sluka Desktop or
  the Sluka extension from a newer zip, changes the shortcuts, or
  uninstalls it.  It needs no Python to open (Sluka Desktop still runs with
  Python).  Section 2.
- The empty white "Sluka Desktop" window that came up with 0.10.0's setup
  was, by its size, one of the windows Sluka keeps out of sight (its worker
  page's, or the doctor's try of the web view), shown.  They now stay
  hidden, whatever asks for them to be shown, and data\logs\sluka-desktop.log
  says so when something did ("was asked to show itself").
- Everything else is as in 0.10.0: the screen read and its keys, the Game,
  Clipboard and Other program tabs, the floating subtitles, mpv and Anki
  (the add-on only says 0.11.0).

New in 0.10.0:

- Keys for the screen (section 7): set in the Screen tab itself, right
  under the box -- "Read the box now", "Select the text box", "Read a box
  once", "Start or stop reading" -- and pressed in the game itself, or in
  any other program: no going out of the game into Sluka for the
  buttons.  They are Windows' own hotkeys, so they work in a game in full
  screen or run as administrator too, and the game does not get the key.
- A setup in a console window (in 0.11.0 a Windows setup took its place).
- .\sluka install-menu --no-desktop / --no-start-menu: one of the two
  shortcuts only.  .\sluka remove-from-pc: what the app put outside its
  folder taken away (the setup's Uninstall does it).
- Everything else is as in 0.9.0: the screen read itself, the Game,
  Clipboard and Other program tabs, the floating subtitles, mpv and Anki
  (the add-on only says 0.10.0).

New in 0.9.0:

- Screen, a new tab of the game text menu (section 7): the text in a box
  of a game's window read off the screen (OCR) and put into the floating
  subtitles -- for a game whose text no hook reads: one in an emulator or
  a browser, one whose engine LunaHook does not know, a film's subtitles.
  Drag the box once over where the game writes; it is kept for that game
  and read again by itself when the game starts again.  Read with one of
  three readers LunaTranslator 12.1.3.12 has, driven as LunaTranslator
  drives them:
    Sluka's own          LunaTranslator's own OCR, with PaddleOCR's
                         PP-OCRv5 model: offline, in the engine folder
                         (engine\ocr); Japanese, Chinese and English
    Windows'             Windows' OCR (Windows 10 and 11): offline, for the
                         languages Windows has the OCR of
    Google Lens          online: each picture is sent to Google (Sluka
                         asks first, the first time)
  "Auto" takes the first of the two offline ones that works here.
- Each text read goes on the clipboard too, where asked, as the game's
  lines do.
- .\sluka ocr-check: the readers tried, and what each reads in a box you
  drag; the doctor says which of them can be used here.
- Everything of 0.8.0 is as it was: the Game, Clipboard and Other program
  tabs, the floating subtitles, mpv and Anki (the add-on only says 0.9.0).

New in 0.8.0:

- Sluka's own engine for game text (section 7).  It comes with the app, in
  its engine folder: LunaHook exactly as LunaTranslator 12.1.3.12 ships it,
  driven exactly as LunaTranslator drives it -- the same calls, in the same
  order, with the same settings -- in a program of the app's own.  Nothing
  is downloaded or installed (the "Fetch LunaHook" button is gone), and
  LunaTranslator is not needed (it can still send its lines through "Other
  program").  The engine puts each line into the floating subtitles, and
  on the clipboard too when "Copy each line to the clipboard too" is
  ticked.
- A game run as administrator: "Hook as administrator" (Windows asks).
- "Read Windows' text functions too", for a game whose engine LunaHook
  does not know; the wait for the rest of a line and the game's code page
  are LunaHook's own settings now, as in LunaTranslator; the game's engine
  is named; LunaHook's messages are in English; a game that draws in
  programs of its own is hooked in all of them.
- Anki, mpv and the floating subtitles themselves are as in 0.7.0 (the
  add-on only says 0.8.0 now).

New in 0.7.0:

- Game text (section 7): a menu that puts a game's text into the floating
  subtitles, as LunaTranslator does.  Choose the game (or click on its
  window); Sluka's text hooker -- LunaHook, the one inside LunaTranslator
  -- reads the text out of the game, lists every place text comes through ("text threads") with
  what each said last, and the one you click goes to the floating
  subtitles, line by line, tidied as LunaTranslator tidies it.  What you
  picked is kept for that game, which is hooked again by itself the next
  time it starts.  The same menu can take the lines from the clipboard
  instead (LunaTranslator or Textractor set to copy them), or straight from
  LunaTranslator's network service or Textractor's WebSocket extension.
- The floating subtitles' button has moved to the bottom left of Sluka's
  windows, off Sluka's own buttons, with the game text button beside it.
- Anki, mpv and the floating subtitles themselves are as in 0.6.0 (the
  add-on only says 0.7.0 now).

New in 0.6.0:

- The floating subtitles (section 6): Sluka's subtitle box in a window of
  its own that stays over every other -- a game, a visual novel, a film in
  another player -- showing the text another program gives it, read as
  Sluka reads a subtitle: words in their colours, the card when you point
  at one, the panel when you click one, the levels, the keys.
- mpv looks more like Sluka.  Windows 11's Japanese fonts (Noto Sans JP,
  Noto Serif JP) are of a kind mpv can only draw at their thinnest, which
  is why kana and kanji were thin; the app now makes plain copies of them
  at the weights Sluka uses, in mpv's fonts folder.  mpv reads that folder
  when it starts, so the first video after the update still has the thin
  letters (drawn a little bolder meanwhile); the next one has the copies.
  Also: a subtitle's two lines are joined as Sluka joins them, levels 3 and
  4 are marked as Sluka marks them, the kana over a headword sit where the
  app's pages put them, and mpv follows Windows' display scale (125 %,
  150 %) as the app's windows do.  [mpv] scale still adds to it.
- Anki: the add-on is 0.6.0 too; restart Anki once after the update.

New in 0.5.1: fixes for mpv and Anki, which 0.4.0 and 0.5.0 on Windows
could not work with.

- mpv: the script's every message to the app was refused by mpv 0.36
  ("argument 4 is not a string" in script.log), so the app never heard a
  player answer.  Fixed in the script (sluka.lua 0.5), which the app writes
  into mpv's scripts folder at its start.
- Anki: the add-on, asked by the app who it was, asked Qt for its web
  profile from the wrong thread, which brought Anki down a few seconds
  after the app connected -- or before its window ever showed.  Fixed in
  the add-on (0.5.1).  The app also leaves alone an Anki that is still
  running the add-on of before, rather than bring it down: restart Anki.
- .\sluka doctor, with the app running, says whether the players and Ankis
  the app found actually answer it, not only that the files are in place.

New in 0.5.0: no browser is needed or used.  The windows are the app's own
-- its title, its icon, its button in the taskbar -- with Windows' own web
view inside them (WebView2, the engine of Edge, which comes with Windows
apart from the Edge browser: uninstalling Edge leaves it in place).  As on
Tails, one more page that is never shown holds Sluka's background worker.

Read this first: the Windows side was written and tested on Linux, against
stand-ins for Windows, its web view, mpv and Anki.  0.5.0's windows have
since run on a Windows PC; the fixes of 0.5.1 have been tried against the
stand-ins only.  "What was tested" below says which parts that leaves
untried, and "When something is wrong" says what to send back.


1. What you need
----------------

- Windows 10 or 11, with its web view (the "Microsoft Edge WebView2
  Runtime").  Windows 11 has it and keeps it up to date by itself; so do
  most Windows 10 by now.  `.\sluka doctor` says whether it is there.
  No browser is needed: Edge, Chrome or another may be there or not.
- Python 3.9 or newer.  Nothing else is installed: the app uses only what
  comes with Python.  For game text, the 64-bit Python (python.org's own
  download is): the engine's host is 64-bit, for 32-bit and 64-bit games
  alike.  `.\sluka doctor` says if yours is not.  For Sluka's own OCR (the
  Screen tab), a Python that came with Microsoft's C++ runtime 14.40 or
  later -- the newest from python.org does; with an older one the other
  readers still read the screen, and the menu and the doctor say so.
- Your own Sluka extension zip (the Chrome edition; this was made with
  sluka-extension 0.7.4).  It is not included.
- If you want them: mpv, and Anki.


2. Installing
-------------

1. Python, if `py --version` or `python --version` in a terminal shows
   none: from https://www.python.org/downloads/windows/ .
   Not one of the "Python 3.x" apps of the Microsoft Store. Windows keeps
   what such an app writes under AppData in a folder of the app's own, so
   Sluka's script would not reach mpv, nor its add-on Anki. (The app says
   so if it finds itself run by one; its own windows work with it.)

2. Double-click Sluka-Desktop-Setup-0.16.2.exe.  Windows asks first, for a
   program from the internet that is not signed: "More info", then "Run
   anyway".  Setup's window has a page at a time:

     Licence agreement  Sluka Desktop's (LICENSE.txt; after it, the
                        notices it points to, NOTICES.txt, and Go's
                        licence, Setup being built with Go): read it, and
                        tick "I accept the licence agreement" for Next
                        (section 15)
     Welcome            and whether Python was found (Next waits for it;
                        "Get Python..." opens python.org's page for it)
     The folder         %LOCALAPPDATA%\Programs\Sluka Desktop, or another
                        (Browse...).  Not under "Program Files": it says
                        why.  A folder with other things in it gets a
                        "Sluka Desktop" folder of its own inside.
     Options            a shortcut on the desktop; Sluka in the Start menu
                        (with "Sluka Desktop Setup" beside it); Sluka's
                        add-on in Anki, where Anki is on this PC; your Sluka
                        extension's zip, the newest one in your Downloads
                        folder filled in (Browse... for another; left
                        empty, it is added later)
     Installing         a progress bar, and what Setup does, line by line
     Done               "Start Sluka Desktop now", then Finish

That is all: nothing to unpack, no files to drag, no terminal.  It
installs for you alone and asks for no administrator.  Sluka Desktop is
then in Windows' list of apps (Settings > Apps > Installed apps), and
Setup keeps a copy of itself in the app's folder, Sluka Desktop
Setup.exe.  Opened again -- "Sluka Desktop Setup" in the Start menu, or
Settings > Apps > Sluka Desktop > Modify, or a newer Setup -- it finds the
Sluka Desktop that is installed and offers, on one page:

     Update Sluka Desktop to <version>     (a newer Setup only)
     Update from a zip                     a newer Sluka extension
                                           (sluka-extension-....zip) or
                                           Sluka Desktop (a newer Setup, or
                                           sluka-desktop-...-windows.zip):
                                           the newest in your Downloads
                                           folder is filled in, with
                                           whether it is newer than yours;
                                           Browse... for another
     Shortcuts                             on the desktop, in the Start menu
     Uninstall Sluka Desktop               your words, books and settings
                                           kept, if you like (section 14)
     Another folder...                     another Sluka Desktop

Your data, config.ini and the extension stay as they are through an update
(the extension unless that is what is updated).  The app has to be
closed meanwhile: Setup says so if it is not.  An update changes all of
the app's files or none: where one is in use -- by a game that Sluka read
text from, say -- nothing is changed, and Setup says to close it and try
again.  A zip (or a newer Setup) dragged onto Sluka Desktop Setup.exe is
filled in.

Coming from 0.16.1, 0.16.0, 0.15.0, 0.14.2, 0.14.1, 0.14.0, 0.13.0,
0.12.5, 0.12.4, 0.12.3, 0.12.2, 0.12.1, 0.12.0 or 0.11.0: the new Setup offers "Update
Sluka Desktop to 0.16.2" on its page after the licence agreement.  From
0.10.0, or an older one unpacked by hand: the new Setup finds it --
through Windows' list of apps, its shortcuts, or the running app -- and
offers the same there.  (Not found: Another folder....)
0.10.0's console setup goes, and its line in Windows' list of apps and its
shortcut in the Start menu become the new Setup's.  Restart Anki once,
after the app's first start.  Windows Security may take some files of the
engine folder away as they are written: Setup says so (section 7).

Without the setup, the zip as before:

1. Unpack sluka-desktop-0.10.0-windows.zip into a folder you may write to,
   for example C:\Users\<you>\sluka-desktop. Not under "Program Files".
   (Before unpacking: right-click the zip > Properties > Unblock, if that
   box is there. Otherwise Windows asks "are you sure" at the first start;
   "More info" > "Run anyway".)
2. Drag your sluka-extension zip onto Sluka.cmd.  Or, in a terminal opened
   in the app folder:

       .\sluka install-extension C:\path\to\sluka-extension-0_7_4.zip

3. To see what the app found on this PC (Python, Windows' web view, mpv,
   Anki) -- it also opens a page in the web view, out of sight, to see
   that it works:

       .\sluka doctor

4. Double-click Sluka.cmd. A console window shows for a moment, then
   Sluka's own window opens.
5. Recommended: shortcuts on the desktop and in the Start menu.  They start
   the app with no console window at all, with Sluka's icon, and pinned to
   the taskbar the shortcut and the open app are one button.

       .\sluka install-menu                  both
       .\sluka install-menu --no-desktop     the Start menu's only
       .\sluka install-menu --no-start-menu  the desktop's only

A newer Sluka later: step 2 again with the new zip, the app closed.  A newer
Sluka Desktop: unpack it over the folder (data, extension and config.ini
are not in the zip, so they stay).

Coming from 0.4.0: your config.ini is kept and gets an [app] section at the
first start.  Words, levels and settings are in data\storage.sqlite and
stay.  Books and dictionaries that were added in 0.4.0's browser are not in
the web view (they were kept by that browser); add them again, or restore a
backup made in Sluka's Settings.


3. Day to day
-------------

- The app runs for as long as one of its windows is open. Minimised is
  fine. With the last window closed the app ends, and mpv and Anki are
  plain mpv and Anki again until it is started.
- Started a second time, it opens one more window of the running app.
- The window menu -- Alt+Space, or a right click on the title bar -- has
  what the menu of the Tails windows has: Reload this page, Larger, Smaller,
  Normal size, Play a video in mpv with Sluka..., Open Sluka's data folder,
  and About; and the floating subtitles, on or off, and whether clicks go
  through them.  Ctrl+plus, Ctrl+minus, Ctrl+0 and F5 work as in a browser.
- Two small round buttons at the bottom left of every window: the first
  turns the floating subtitles on and off (section 6), the second opens the
  game text menu (section 7); its dot is green while a game's text is
  coming in, amber while it waits for one, blue for the clipboard or
  another program.  If they are in the way of something of Sluka's, drag
  them elsewhere: they stay there.  [bar] button in config.ini starts them
  in another corner, or takes them away.
- A video in the app's own player can go full screen; Esc comes back.
- A link to a website opens in your own browser (whichever is your
  default); the app's windows show nothing but Sluka.
- What the web view keeps for the app (books, dictionaries, films) is in
  data\webview2, apart from anything else on the PC.
- The network is used directly ([network] mode = direct), so machine
  translation, online dictionaries, downloadable voices and packs, and the
  like work as in the extension.  For reading aloud, the voices Windows
  itself has are there (Settings > Time & language > Speech adds more).
- Settings → Sync & backup's backup folder is chosen in Windows' own
  folder window and stays chosen: in Google Drive (G:\My Drive\Sluka),
  OneDrive, or anywhere.  Only that folder is reached, nothing beside it.
  Exports that Sluka "downloads" are written to data\Downloads; so is
  anything a page downloads by itself.
- What you read and hear in mpv, the floating subtitles and Sluka Vision
  counts on Sluka's Home page as what you read and hear on its pages does:
  mpv's films as Listening (those Sluka can tell are in a language you
  learn), and their subtitle lines as subtitle words; the text of the
  floating subtitles and of Sluka Vision as Reading, at your own pace; and
  half the time a game is played as Listening.  See "New in 0.12.3" above
  for the rules.


4. mpv
------

At every start the app writes its script, sluka.lua, where mpv reads
scripts:

    %APPDATA%\mpv\scripts            mpv
    %APPDATA%\mpv.net\scripts        mpv.net, if that folder exists
    <mpv>\portable_config\scripts    an mpv that keeps its settings beside
                                     itself, where the app finds one
                                     (Scoop's mpv is such a one)

From then on, any video opened in mpv while the app runs has Sluka in it,
with Sluka's look, as on Tails: the subtitle line cut into words in their
colours, the card when you point at a word, the panel when you click one.
An mpv that was open before the script was first put there has to be
opened again.

- When a film will not play in the app's own player, the app offers to
  play it in mpv, as on Tails: say yes, and choose the film (and its
  subtitles) once more -- a web page is never told where its file is.
  The window menu's "Play a video in mpv with Sluka..." does the same.
- An mpv in a folder of its own that the app did not find (unpacked from a
  zip, with a portable_config folder): say once where it is.

      .\sluka install-mpv C:\path\to\mpv

- To start mpv with the script without relying on the scripts folder:

      .\sluka mpv C:\films\film.mkv [C:\films\film.srt]

- Everything Sluka draws in mpv larger or smaller: [mpv] scale in
  config.ini (1.3 = three tenths larger).  It follows Windows' display
  scale by itself; [mpv] scale is on top of that.
- Fonts: mpv draws only the thinnest of a "variable" font, the kind
  Windows 11's Noto Sans JP and Noto Serif JP are.  So where Sluka uses
  one, the app writes a plain copy of it at each weight Sluka draws it at
  into mpv's fonts folder (%APPDATA%\mpv\fonts, Sluka-....ttf), once, and
  mpv uses those.  mpv reads the folder as it starts: a player that was
  already open draws those letters a little bolder instead, until opened
  again.  Only a font whose own licence allows a changed copy gets one:
  the Open Font License of Noto's does; the fonts Microsoft supplies with
  Windows say "any other use is prohibited", and mpv draws them as they
  are.
- The script's own notes: %LOCALAPPDATA%\sluka-desktop\mpv\script.log.
  Neither it nor the app's log holds the names of your files.
- mpv has to be a build with Lua, which the Windows builds linked from
  https://mpv.io/installation/ are.

How the two meet: the script has mpv open a named pipe called
sluka-mpv-<process number>, and the app looks for pipes of that name. If
your mpv.conf already sets input-ipc-server, that pipe is left as it is
and used.


5. Anki
-------

    .\sluka install-anki

puts the app's add-on into %APPDATA%\Anki2\addons21\sluka_desktop. If your
Anki keeps its things elsewhere, name that folder (the one that holds
addons21):  .\sluka install-anki D:\Anki2 . Then restart Anki.

With the app running, the words of the card under review are Sluka's:
point at one for its card, click it for its panel. Without the app, Anki
is as it always is. The add-on's options are in Anki under Tools >
Add-ons > Sluka Desktop > Config.

The app keeps the add-on in step with itself: after an update of the app,
its first start brings the add-on up to date, and Anki wants a restart.

- Sluka's own files are not copied into Anki: the add-on folder gets a
  link ("junction") named ext to the app's extension folder. If you move
  the app folder, start the app once and restart Anki. To have real copies
  instead (about 200 MB):  .\sluka install-anki --copy
- How the two meet: the add-on listens on a port of this computer's own
  address (127.0.0.1) and writes the number, with a random word, into
  %LOCALAPPDATA%\sluka-desktop\anki. Only a program that says the word is
  answered.
- Sluka's own Settings > Anki (sending words to Anki through the
  AnkiConnect add-on) is a different thing and independent of this.

Cards from games and films.  With Settings → Anki's word panel button on
(the extension's own, through AnkiConnect, as on a page), the panel of
the floating subtitles, of Sluka Vision and of mpv has the Anki key in its
head, left of the cross: a click on it, or its key -- P unless Settings →
Keys says otherwise, while the panel is open; over a game too, as Sluka
Vision's grading keys are -- puts the word on the list of picks with the
sentence it stands in, filed at level 1 if it was new, and the
extension's next round makes its card a moment later, with your note
type, into your deck for picked words, with what Settings → Anki puts on
cards.  Its mark says how the word stands: a plus, waiting, in Anki (a
tick: pressed again, it opens the card in Anki).

- A game's card (the floating subtitles with the game hooked in the Game
  tab, or Sluka Vision) gets the line's sound and a picture of the game,
  as Settings → Anki → Media asks.  The sound is the game's own: while
  the game is hooked, or its window is the one Sluka Vision reads, Sluka
  keeps the last minute of that program's sound (and its children's) --
  not your music, a call or Sluka's own voice -- in memory, nowhere else;
  it is let go of when the game is.  A clip runs from a little before its
  line came to where its voice stops (over the game's music too) or the
  next line came, twelve seconds at most; with "With the sentence before
  and after", from the line before to the end of the line after, and the
  card's sentence holds them.  The picture is the game's window as it is
  when the word is picked, without Sluka's words over it.  Where the
  video is chosen, the picture goes instead: a game's video cannot be
  made.  Windows older than 10 version 2004 cannot give Sluka one
  program's sound: the cards go without it, and the menu says so once.
- A film's card (mpv) gets its line's sound read out of the file itself,
  a quarter second before the line to a little after it, as Sluka's
  videos page reads a video file of yours (MP4, MKV, WebM; a sound track
  that cannot be read there -- AC-3, DTS -- gives no clip), the frame on
  screen without the subtitles, and the video of the line where it is
  chosen.  "With the sentence before and after" takes the line before.

The panel's speaker.  In the head's top left corner, as in the
extension's panel: a click, or V, says the word -- the voices of
Settings → Voice, Google Translate's standing in for a cloud voice where
none is set up, so every language is heard without a download.  Its
sound is Sluka's own, not the game's: it is not on a card's recording.

The panel's other keys.  Left of the Anki key, as in the extension's own
panel: Translate puts the word into Google Translate and shows its
translation in the panel; Look up opens the menu of the dictionary sites
Settings lists for the language, each in a small window of Sluka's own
(over the game too; it keeps its own web data, in
data\webview2-dictionaries, apart from the app's).  For the dictionaries
their makers publish for anyone to use, the menu has the same dictionary
offline as well, under the site:

     Wiktionary        every language     from kaikki.org
     JMdict            Japanese (Jisho)   from the EDRDG
     CC-CEDICT         Chinese (MDBG)     from MDBG
     CC-Canto          Cantonese          from Pleco Software
     Folkets lexikon   Swedish            from KTH

Its first click opens its window, which says how large it is and offers
Install: it is downloaded from its makers' own site, read into a file of
Sluka's (data\dictionaries), and the word shown, offline, from then on
-- and any other word typed into the window.  Its foot says whose it is,
under which licence, and has Remove.  The other sites (Weblio, Naver,
Larousse, Duden, ...) keep their dictionaries to themselves: online
only.  A download follows config.ini's [network] mode, as all of Sluka's
do: none offline (the window says so, and how to change it), through Tor
in tor mode, directly otherwise.

Your own dictionaries.  Those added to Sluka in Settings → Dictionary →
"Your own dictionaries" are in the panel as in the extension's own:
their meanings drawn as each dictionary lays them out, under its name,
and where Settings says there -- instead of Sluka's meanings (as it
comes), under them or above them.  A word none of yours has shows
Sluka's.  A link in them opens in a small window of Sluka's.  In mpv,
and in the small card of a word pointed at, they are plain text.

In the app, that card's "Add a dictionary…" takes more kinds of file
than the extension reads by itself.  A dictionary in any of these is
made into a Yomitan dictionary on this computer first, then handed to
the extension as if you had picked that -- it asks what it asks, and
keeps it as any other:

     StarDict          the .ifo with its .idx and .dict (or .dict.dz),
                       and its .syn: pick them together
     ABBYY Lingvo      .dsl or .dsl.dz
     JMdict            JMdict or JMdict_e, or gzipped
     CC-CEDICT         cedict_ts.u8 and the like, or gzipped
     CC-Canto          its .txt, or its zip
     Folkets lexikon   its .xml
     Wiktionary        kaikki.org's .jsonl, or gzipped

Any of them may come in a .zip or a .tar (.tar.gz, .tgz, .tar.bz2,
.tar.xz).  A Yomitan dictionary or a table goes to the extension as it
is, as before.  The card lists it under its own name (a StarDict's or a
Lingvo file's, or the kind's), and the same file added again is
"already added".  While it is made, the line under the button says how
far it has come: a large one (JMdict, a Wiktionary language) takes a
minute or two.  The files are read in data\dictionaries\files, and
taken away once the extension has the dictionary.  MDict (.mdx),
Babylon (.bgl) and Lingoes files are not read here: pyglossary, for
one, makes them into StarDict or Yomitan dictionaries.

The AI check's ✦.  As in the extension's panel, where Settings → AI
check is on: a key in the head, where the dictionary has the word and
this is a second opinion; for a word that no dictionary has, a button
in the meanings, "Ask AI if this is a real word", with what pressing it
sends.  Pressed, or F (Settings → Keyboard, "Check with AI"; in mpv
only while the panel is open, as F is full screen otherwise), the word
-- and its sentence, where Settings → AI check says so -- goes to the AI
that it sets up, with the key you gave it there, through the
extension's own worker.  What comes back is drawn under the meanings:
whether it is a real word and how sure, its meaning, an example, where
it is used, why -- and under "Your question", the answer to the request
written in Settings → AI check → Advanced → "Your own request" (what it
means here, how its sentence changes it, its background, ...), asked
with every word and nothing to type.  Each press is a request on your
own key: a word answered is not asked again while its panel is open.


6. The floating subtitles
-------------------------

Sluka's subtitle box, on its own, over every other window: what another
program puts into it is shown as Sluka shows a subtitle, with Sluka's own
word list, dictionary and look.  A word graded there is graded in your
books and films too.  It is for text that comes from elsewhere -- a game,
a visual novel, a text hooker, a script of your own -- in the way
LunaTranslator's floating window is.  It shows what it is given: a game's
text from the game text menu (section 7), or any line another program
puts into it.

On and off: the subtitles button at the bottom left of Sluka's window, the
window menu, or  .\sluka bar  (on, off, or the other of the two).  It is
on again at the next start if it was on when the app ended.  It goes with
the app: closing Sluka's last window puts it away too.

Putting text in, from any program on this PC:

    .\sluka bar-text "ある春の日"
    .\sluka bar-text -                  (the text from what is piped in)
    http://127.0.0.1:47821/__sluka__/api/bar/text?text=...
    POST to the same address: the text as it is, or JSON {"text": "..."}

Empty text clears it.  A line in another of the languages you learn than
the one Sluka is set to says so: --lang ja, &lang=ja, or "lang" in the
JSON.  Web pages cannot put text in (the browser says where a request
comes from, and the app refuses one from a website).

With the pointer on it, its width shows, with handles at its ends to make
it wider or narrower, and its buttons over its right end:

    the dots          move it (dragging the subtitle itself does too)
    A- A+             smaller, larger
    the lock          keep it where it is: dragging it does nothing then
    the arrow         let clicks go through it to what is under it, as
                      LunaTranslator's "click through" does; while they do,
                      hold Ctrl to use the bar, or click the small round
                      button at its left to take the clicks back
    the cross         put it away

Point at a word for its card, click it for its panel, as in Sluka; the
panel's buttons set its level.  A click on the bar does not take the
keyboard from the program under it, so the keys that grade work only
where the bar has the keyboard; the buttons work always.  Dragged to
another screen, it moves there.  Where it is, how wide and how large are
kept in data\bar.json.

Its words are read by the same part of Sluka that reads mpv's subtitles,
which runs whether or not mpv does ([mpv] enabled).  If clicks going
through ever make it vanish on your PC, untick "Clicks go through the
floating subtitles" in the window menu.


7. Game text
------------

The game text menu -- the second of the round buttons at the bottom left
of Sluka's window -- says where the lines in the floating subtitles come
from, or lays a game's words over the game itself (Sluka Vision).  Its five
tabs: Game, Screen, Clipboard, Sluka Vision, Off.

Game.  Sluka reads the game's text itself, with its own engine: LunaHook,
the text hooker inside LunaTranslator, by HIllya51 (open source, GPL-3.0),
the successor of Textractor, which knows how hundreds of game engines hold
their text -- KiriKiri, SiglusEngine, RealLive, BGI, CatSystem2, YU-RIS,
Artemis, Ren'Py, Unity, RPG Maker, TyranoScript and many more.  It comes
with the app, in the engine folder: the very files of LunaTranslator
12.1.3.12, driven the way LunaTranslator drives them.  Nothing is
downloaded, and LunaTranslator is not needed.

1. Start the game, then in the menu choose it from the list (programs
   with a window; the ones used before marked with a star) and "Hook".
   Or "Or click on the game's window", then click the game within ten
   seconds.  The floating subtitles come on.
2. Advance the game's text once or twice.  Every place in the game that
   text comes through shows as a "text thread", with what it said last
   and its hook's name and code; the game's engine, as LunaHook found it,
   shows beside the game's name.  Click the thread with the game's lines:
   from then on each new line goes to the floating subtitles.  Tick a
   second one to have both together (a character's name and the line).
   Until you click one, the thread that most looks like dialogue is
   picked by itself (marked "picked by itself"); a click changes it.
3. That is kept for the game (by its program file): next time, the same
   thread is picked as soon as it shows, and with "Hook this game by
   itself when it starts" ticked, the game is hooked as soon as it runs,
   while the app does.  "Forget this game" forgets it.

"Copy each line to the clipboard too", under the threads, puts every line
the engine reads on the clipboard as well, for any other program that
reads it (a dictionary, a card maker); it is kept out of Windows'
clipboard history.

A game whose engine LunaHook does not know shows no thread with its lines.
Two things to try, as in LunaTranslator:

- "Read Windows' text functions too", in the game's card: the text that
  Windows itself draws for the game (GetGlyphOutline, TextOut, DrawText
  ...) shows as more threads.  Kept for the game.
- A "hook code" (an "H-code": HS-4@1234:game.exe) that others found --
  search for the game's name with "hook code".  Type it under the threads
  and "Add": the game gets it at once, and every time it is hooked again.

Text settings, as LunaTranslator has them:

    Wait for the rest of a line   LunaHook sends a thread's text as one
                                  line once the game has been quiet this
                                  long: 0.5 s, as in LunaTranslator.
                                  Longer for a game whose lines come in
                                  pieces, shorter to wait less.
    The game's text is in         for a game whose text is not Unicode:
                                  Japanese (Shift-JIS) unless you say
                                  another, or "As each hook finds it".
    Letters sent more than once   some engines draw each letter two to
                                  four times (KiriKiri: "ここんんににちちはは");
                                  undone by itself, or say how many times.
    Join the lines the game breaks   where its text box ends.
    Take out the game's layout codes   [r], {w}, <color=...>, \C[2], and
                                  readings written after a word.
    Pick the dialogue by itself, Hook games used before when they start.

"What the engine says" shows what LunaHook says as it works (in English):
send it along if something does not go as it should.

- A game run as administrator cannot be reached by a program that is not
  run as administrator: the menu says so and offers "Hook as
  administrator".  Windows asks you first; then the hook goes into the
  game as administrator and talks to Sluka as usual -- the way
  LunaTranslator does it.  (Or start Sluka itself as administrator.)
- One game at a time, 32-bit or 64-bit: the engine puts the hook of the
  game's own kind in.  A game that draws in programs of its own (NW.js,
  some CEF and Unity games) is hooked in all of them.
- The engine runs in a program of its own (Python with app\sluka_desktop\
  hookd.py, with no window), started by the app when a game is first
  hooked, and ended with the app or when another tab is chosen; as it
  ends, it lets go of the game.  If it stops, it is started again and the
  game hooked again.  Its notes: data\logs\hookd.log.
- A text hooker works by putting a small library into the game, which is
  what some viruses do too: Windows Security may take the engine's files
  away, or warn.  If it does, the menu says which file is missing: allow
  it in Windows Security > Virus & threat protection > Protection history
  (or add the engine folder to its exclusions), and unpack the zip again.
  engine\ENGINE.txt lists the files and their checksums.
- LunaTranslator, Textractor or another text hooker that is hooked into
  the same game keeps it from Sluka: close it first.  The menu says so
  when a game does not connect.
- A game in an emulator (yuzu, PPSSPP ...): hook the emulator before it
  loads the game.

Clipboard.  Every text copied in another program goes to the floating
subtitles: set LunaTranslator or Textractor to copy what it reads (or
copy a line yourself).  Text copied in Sluka's own windows is left alone,
and so is text longer than a line.

(The Other program tab, which took lines from LunaTranslator's network
service or Textractor's WebSocket extension, is gone since 0.12.0: set
them to copy each line, and use the Clipboard tab.)

Off.  Nothing is taken; the floating subtitles still show what is sent to
their address (section 6).

To try the engine on its own, in a terminal in the app folder (with the
game let go in the menu first):

    .\sluka hook-check               start the engine and say whether it runs
    .\sluka hook-check --list        the programs with a window, and their numbers
    .\sluka hook-check 4242          hook program 4242 for 40 s and print
                                     every text thread's lines as they come
    .\sluka hook-check 4242 --admin  the same, the hook put in as administrator

Screen.  The text in a box of the game's window, read off the screen
(OCR), for a game whose text no hook reads: a game in an emulator or a
browser, one whose engine LunaHook does not know, a film's subtitles in
another player.  Slower than a hook, and only as good as the picture: a
hook, where one works, gives the game's own text.

1. "Read with": "Auto" takes the first of the offline readers that works
   here, or choose one (each says whether it can be used here, and why
   not):

     Sluka's own          LunaTranslator's own OCR -- PaddleOCR's PP-OCRv5
                          model, run by ONNX Runtime -- in the engine
                          folder (engine\ocr, as LunaTranslator 12.1.3.12
                          ships it).  Offline; Japanese, Chinese, English.
     Windows'             Windows' OCR (Windows 10 and 11), for the
                          languages Windows has the OCR of: Japanese's
                          comes with the Japanese language (Settings > Time
                          & language > Language & region), or alone, in
                          PowerShell as administrator:
                            Add-WindowsCapability -Online -Name "Language.OCR~~~ja-JP~0.0.1.0"
     Google Lens          online, and good at text over pictures: each
                          picture of the box is sent to Google (through Tor
                          where [network] mode = tor; never where it is
                          offline).  "Auto" never takes it.

2. Have the game's window open, then "Select the text box": the screen
   darkens, and you drag a box over where the game writes its text (the
   name box too, if you want it).  Right-click, or click without dragging,
   to stop.  Sluka's own windows are not in the picture you drag on: a
   game behind Sluka's window shows as it is.
3. The window under the box is the one read, from then on: each new text
   in the box goes to the floating subtitles, its lines made one ("Join
   the box's lines into one"), and to the clipboard too if "Copy each text
   read to the clipboard too" is ticked.  The menu shows what was read
   last, when, and by which reader.  "Read now" reads it at once; "Stop"
   stops (and the game is not read again by itself while it runs).
4. The box is kept for the game (by its program file), where it is in the
   game's window -- a window made bigger takes the box with it.  When the
   game starts again, its box is read again by itself.  "Forget this box"
   forgets it.  A box over no window (the desktop) is read where it is on
   the screen, and is not kept.

Keys.  The buttons, as keys, pressed in the game -- or in any other
program -- while the Screen tab is the one chosen: no going out of the game
into Sluka.  They are under the box in the menu: click a key's box, then
press the keys (Esc alone: none; × takes the key away).  They are kept,
and held again whenever the Screen tab is chosen.

    Read the box now        the box read at once (where it is not being
                            read, reading starts)
    Select the text box     a new box dragged, as with the button (pressed
                            again while you drag: stopped)
    Read a box once         a box dragged over anything -- a word in a
                            menu, a sign -- read once into the floating
                            subtitles; the game's own box stays as it was
    Start or stop reading   as "Stop", and back

- A key is one with Ctrl, Alt or Win -- Ctrl+Shift+R, Alt+F2 -- or one of
  those that type nothing: F1 to F11, F13 to F24, Pause, Scroll Lock,
  Insert, Print Screen, alone (F12 alone is Windows' own, for debuggers).
- They are Windows' own hotkeys, as AutoHotkey's are: they work over a
  game in full screen, or one run as administrator, and while Sluka has a
  key, the program in front does not get it.  A key that another program
  (or Windows) has already cannot be had: the menu says so, and you choose
  another.
- Ctrl+Alt is AltGr on many keyboards (AltGr+S is "ș" on a Romanian one):
  Ctrl+Alt with a letter types nothing while Sluka has it.  The menu says
  so; Ctrl+Shift or Alt+Shift keep AltGr free.
- While you choose a key in the menu, Sluka lets go of all of them, so that
  what you press reaches the menu.

Reading settings:

    When to read          As the text changes: once the box has changed and
                          then stood still a moment (a line that comes a
                          letter at a time is read when it is all there).
                          Every few seconds (0.5 to 5 s): for a film's
                          subtitles, over a picture that never stands
                          still.  After a click or a key: once the game is
                          clicked, or Enter or Space pressed in it.
    The text is written   either way, across, or down (vertical text, read
                          in columns from the right).
    Leave out furigana    the small kana over a word, that tell how it is
                          read, are not part of the line.
    Read only while the game is in front
                          what another program shows over the game is not
                          read.  Sluka's own windows are never read.
    What is read          what the screen shows there; or the game's own
                          window, drawn by itself, where something covers
                          the box -- and then Sluka shows in screenshots
                          and recordings (not every game draws one: the
                          screen is read where it does not, and the menu
                          says so).
    Windows' OCR reads    the language, among those Windows has the OCR of.

While a box is read off the screen, Sluka's own windows -- the floating
subtitles included -- are left out of every picture of the screen, so that
the subtitles are never read back, and a box behind Sluka's window is read
all the same: screenshots and recordings made meanwhile do not show them
either (they still show on the screen).  To have them in your recordings,
read the game's own window ("What is read"): nothing of Sluka's is in that
picture, so nothing needs leaving out (only while a box is dragged).
Windows before Windows 10 2004 cannot leave windows out: there Sluka's
windows step aside while the box is dragged, and reading waits while Sluka
is in front.

The screen is read by a program of its own (Python with app\sluka_desktop\
ocrd.py, with no window), started when the Screen tab is chosen and ended
with the app or when another tab is; if it stops, it is started again.
Its notes: data\logs\ocrd.log ("What the screen reader says", in the
menu).

Sluka Vision.  The words of a game's whole window, read off the screen and
laid over the game where they sit, as YomiNinja lays them: for a game whose
text is all over its window -- Persona's slanted replies, the names on its
signs and shops, menus, maps -- rather than in one box.  Nothing is written
over the game's own letters: each word you are learning is underlined in
the colour its level has on Sluka's pages (new words blue, levels 1 to 4
amber), left of it in a column of vertical text; words you know have no
line.  Point at a word: its card.  Click it: its panel, with the levels to
file it at (a new word clicked is filed at level 1, as on Sluka's pages;
its own level, clicked again, puts it back to New); click the word again,
or the panel's x, to close the panel.  While a panel is open, Sluka's keys
grade it in the game -- 1 to 4, K, X, 0 back to New, as Sluka is set -- and
Esc closes it: the game has those keys back the moment the panel closes.
Its 👀 says how many times you looked the word up, from the third time, as
Sluka's own panel does (a click is a lookup, here as on Sluka's pages).  The floating
subtitles rest while this tab is chosen (they come back after it, if they
were on).

1. Play the game in a window, or a borderless window: nothing can be laid
   over a game in exclusive full screen (YomiNinja can't either).
2. In the game, press Alt+S: the window in front is read whole, and its
   words are laid over it within a second or two ("Sluka Vision ·
   reading..." at the game's top right meanwhile).  Or, in the tab, "Choose
   the window", then click on the game.  The tab shows the window read,
   what was read last, when, and how long it took.
3. "Read again by itself as the window changes" (ticked as it comes):
   from then on the window is read again each time what it shows has
   changed and then stood still a moment -- the next line of dialogue, a
   new menu, the camera turned.  Whatever the game moves by itself all the
   time (a character breathing, rain, a video) is not waited for.  Untick
   it to read only when Alt+S is pressed.
4. Whichever way it was read, the words of a line go as soon as what
   changed under them stands still (the dialogue moved on: within half a
   second), so that no word is left under text that is no longer there;
   the window made larger, all of them at once.  Not while it moves, nor
   where it keeps moving: text on a button that bobs or glows keeps its
   words and its card.  What is under them again as it was read (the
   button the pointer lit, dark again): they are back.  The word you point
   at keeps its card while the pointer is on it.  Alt+V puts them all
   away; Alt+S, or the next change, brings the new ones.
5. Another program in front: the words are out of sight until the game is
   in front again.  The game's window moved: they move with it.

Read with:

    Google Lens          (as it comes) the most accurate at a whole
                         window: Japanese, Chinese, Korean, English and
                         more, slanted lines and columns of vertical text,
                         each word where it is.  Online: each read sends a
                         picture of the game's window to Google (a window
                         larger than full HD is sent smaller).  Through Tor
                         where [network] mode = tor; never where it is
                         offline.  A read takes about a second.  Sluka
                         asks before Google Lens first reads (section 15);
                         until a yes, Sluka's own OCR reads.
    Sluka's own, Windows' OCR
                         offline, as in the Screen tab: each line where it
                         is, its letters spread over it (no word places).

Keys, in the tab (as in the Screen tab: click a key's box, then press the
keys; x for none), held while the Sluka Vision tab is chosen:

    Read the window             Alt+S as it comes (YomiNinja's): the window
                                in front -- the game, pressed in the game;
                                pressed in Sluka's window, the one read before
    Read by itself: on or off   none as it comes
    Put the words away          Alt+V as it comes (YomiNinja's)
    Pause the game: on or off   Alt+P as it comes (below)
    Freeze the picture: on/off  Alt+F as it comes (below)

The game stopped where it is.  To read a line at leisure -- a cutscene's
subtitle, dialogue that moves on by itself, a voice line -- either of
two keys stops the game where it is, each its own way: try the one, and
keep to the one that suits each game.

Pause the game (Alt+P): its picture is taken at once, then the game
itself is paused -- every one of its threads held, as Resource Monitor's
"Suspend process" holds a program: its picture, its sound, its cutscene,
its timers stop where they are.  The picture taken is laid over its
window meanwhile, with the words read on it (a line not read yet is read
off it), and takes the clicks: Windows fades the window of a program
that does not answer, and would offer to close it on a click.  "Game
paused · Alt+P to go on" at its top left.  Alt+P again: the game goes on
where it was, and the picture is taken away a moment later, once the
game has drawn itself again.  What you typed into the game meanwhile
reaches it then.  A game run as administrator, or one an anti-cheat
guards, is not Sluka's to pause: its picture is frozen instead, and a
message says so.  Leave online games alone: one paused for long may lose
its connection.

Freeze the picture (Alt+F): only the picture is kept over the window,
the words on it; the game goes on behind it, its sound too -- for a game
that should not be paused.  Clicks on the picture are not the game's;
its keys still are.  Alt+F again: the game's own picture again, read as
it is.

The other key while one is on switches to it, the same picture kept.
The tab's "Pause the game" and "Freeze the picture" buttons do the same.
Meanwhile a word's card has the picture kept, and the window itself is
not looked at: its key reads the picture again.  Another tab chosen,
another window read, the game closed: the game goes on.  Where Sluka is
ended by force while a game is paused, the game goes on when Sluka
starts again (or in Resource Monitor: right click it, Resume process).


Sluka Vision settings: "Leave the furigana out" (the small kana over a
word, ticked as it comes); "What Sluka Vision reads": what the screen shows
there, or the game's own window, drawn by itself, where something covers
it -- and then its words show in screenshots and recordings.  The language
Windows' OCR reads is the Screen tab's.

The words' window is Sluka's own, laid over the game's: over every other
window, see-through, taking the pointer only where there is a word, a card
or a panel -- everywhere else the game is clicked as if Sluka were not
there -- and never the keyboard (the game keeps it: Sluka's grading keys
are held for an open panel, and given back as it closes).  While what the
screen shows is read, it is left out of every picture of the screen
(Windows 10 2004 and later), so that it is never read back -- and so are
Sluka's other windows: screenshots and recordings do not show them.  While
the game's own window is read, they all show in screenshots and
recordings: nothing of Sluka's is in the game's own picture.  Where that
picture cannot be had (the game gives none, or Windows enlarges its window
for a 125 % or 150 % screen), the screen is read there, and Sluka is left
out of pictures for that game meanwhile; the menu says so.  A game drawn
with the graphics card past Windows may leave an old picture in its window
(Ace Attorney: its title menu): Sluka then takes the window as Windows
itself draws it, which follows the game, and its words still show in
recordings.  Where that picture too stands still while the screen shows
the game going on -- looked at only while the game is in front -- the
screen is read there instead, and a message says so, once a game: Sluka
needs the switch to read the game right, and its words are left out of
screenshots and recordings of that game meanwhile (the tab chosen again,
or what it reads set otherwise and back, tries the game's own window
afresh).  The Screen tab does the same for its box.  Windows before
Windows 10 2004 cannot leave windows out: read the game's own window there.

Sluka Vision reads with a program of its own, as the Screen tab does
(Python with app\sluka_desktop\ocrd.py, with no window), started when
the tab is chosen and ended with the app or when another tab is.  Its
notes: data\logs\ocrd-vision.log ("What the screen reader says", in the
tab).

To try the readers on their own, in a terminal in the app folder:

    .\sluka ocr-check                which readers can be used here, and why not
    .\sluka ocr-check --read         drag a box over some text: each offline
                                     reader reads it, and says how long it took
    .\sluka ocr-check --reader lens  the same with one reader (Google Lens only
                                     this way: it sends the picture to Google)


8. Settings
-----------

config.ini in the app folder, written at the first start, with a comment
on every line. The ones Windows adds:

    [app] shell = auto               webview2 (the app's own windows), or
                                     browser; auto = webview2 where Windows
                                     has its web view, else a browser
    [app] port = 47821               the address of the app's pages on this PC
    [app] web_security = off         see "Security notes"
    [app] pickers = no               yes: Sluka may use the engine's folder pickers
    [network] mode = direct          or offline, or tor (with socks = host:port)
    [window] devtools = no           yes: F12 and the window menu open the
                                     web view's developer tools
    [webview2] runtime =             a fixed-version WebView2 Runtime's folder,
                                     instead of the one Windows has
    [webview2] args =                more switches for the web view's engine
    [browser] ...                    only for shell = browser: as in 0.4.0
    [mpv] scripts = , player =       written by  .\sluka install-mpv
    [links] external = open          or ask, or ignore
    [bar] enabled = yes              the floating subtitles (section 6)
    [bar] button = bottom-left       where their button and the game text
                                     button are in the app's windows:
                                     bottom-right, top-left, top-right,
                                     or none
    [games] enabled = yes            the game text menu (section 7)
    [games] engine =                 another folder with the engine's
                                     files (empty: the engine folder)

Change the port only if another program has it: the web view files your
books and dictionaries under the address, and a changed port hides them
until it is changed back.  (A config.ini of 0.4.0 has the port and
web_security under [browser]; they go on being read there.)


9. Your data
------------

Everything is in the app folder, under data\ :

    data\storage.sqlite   your words, their levels, Sluka's settings
    data\webview2\        what the web view keeps: books and dictionaries
    data\Downloads\       exports (and backups set up before 0.16.1)
    data\folders.json     the folders chosen for Sluka (its backup folder)
    data\logs\            sluka-desktop.log, crash.log, and the game
                          text engine's notes, hookd.log, and the screen
                          reader's, ocrd.log
    data\sluka.ico        Sluka's icon, made from the extension's
    data\bar.json         where the floating subtitles are, and how set
    data\gametext.json    the game text settings, and for each game its
                          text thread, hook codes and "hook by itself"
    data\screentext.json  for each game, the box read on the screen
    data\mpv-fonts.json   which fonts were copied for mpv (section 4)

Sluka's engine for game text, and the screen's readers (engine\ocr), are in
the engine folder, beside app: they are part of the app, not of your data.

To keep a copy, close the app and copy the data folder. Nothing of the app
is written elsewhere, except the mpv script and the fonts copied for mpv,
the Anki add-on, the shortcuts, and the small folders under
%LOCALAPPDATA%\sluka-desktop.

From Tails to Windows: the way Sluka itself offers is a backup made in its
Settings on Tails and restored here. Failing that, with both apps closed,
copy data/storage.sqlite from the Tails folder to data\ here before the
first start: that brings the words and settings. Books and dictionaries
have to be added again either way; the two systems' web engines keep them
in forms the other cannot read.


10. What is different from Tails
--------------------------------

- The web engine is Windows' WebView2 (Chromium, as in Edge), not
  WebKitGTK.  Video in the app's own player is whatever it plays, which
  is more than WebKitGTK does: H.264 and AAC included.
- Online by default; on Tails, offline by default.
- The app's pages are served to its web view at http://127.0.0.1:<port>,
  where on Tails they come through the web view directly, with no network
  socket.
- The floating subtitles, game text and the screen read are Windows' only.
- Tails itself stays on version 0.3.0. Nothing in it changes.


11. What was tested, and what was not
-------------------------------------

Tested on Linux, with the same code that runs on Windows:

- The app's whole Windows shell -- its windows, the never-shown page of the
  worker, the window menu, full screen, downloads, permissions, a page
  that crashed, closing by the page, by window.close() and by the user, the
  end when the last window closes, a second start opening a window --
  against a stand-in WebView2 whose objects are real COM objects reached
  through their tables with ctypes, as the real one's are, and a stand-in
  Windows.  The stand-in's tables were written out, method by method, from
  two independent translations of Microsoft's WebView2.h, and every place
  in a table the app calls was checked against both.
- The same with the app's real HTTP front, its pages and the page script's
  calls naming their window.
- mpv: the real script and the real app over stand-in pipes; and (new in
  0.5.1) the real script run in a stand-in mpv whose functions answer as
  mpv 0.36's do, through a whole conversation with the app: hello, its
  look, a line, its words drawn, a word pointed at, clicked, graded, a
  Japanese line, a long one broken into rows, the player closing.
- Anki: the real add-on in a stand-in Anki, met by the app's real code over
  the port as on Windows; (new in 0.5.1) its Qt refuses to make a web
  profile off Anki's own thread, as the real one cannot -- the add-on of
  0.5.0 falls into exactly that, the one of 0.5.1 does not.
- (New in 0.6.0) The floating subtitles: their page in a real Chromium
  (Chrome, which is what Windows' web view is) with a stand-in for Sluka's
  engine -- a line, its words in their colours, a card, a panel, grading
  by button and by key, moving, sizing, the bar's buttons -- and
  photographed beside your screenshots of Sluka's own subtitles, card and
  panel; their window and the app's side end to end, against the stand-in
  Windows: made, shaped to what the page draws, clicks through and back,
  Ctrl, another screen, the window menu, the command line, the address
  for other programs, the bar back at the next start.
- (New in 0.6.0) The copies of variable fonts, against FreeType and
  fontTools: the same letters as the font at that weight.
- (New in 0.8.0) Game text: Sluka's engine (hookd.py) loading a stand-in
  for LunaHost64.dll -- a library of the same functions, built for the
  tests -- by the same declarations LunaTranslator uses, through the whole
  conversation: LunaHook's messages asked for in English (each one's
  placeholders checked against LunaHook's own), LunaTranslator's settings,
  a game hooked (by a stand-in for LunaSubprocess's dllinject), connected,
  its threads and lines, its engine, threads synced, hook codes, Windows'
  text functions, let go and hooked again, a game hooked already, one
  that cannot be opened, one that never connects, a library that cannot
  be loaded, an engine that stops (started again) and one that keeps
  stopping (left).  The app's side end to end against it: the dialogue
  picked by itself, picking by hand, two threads together in the order
  picked, what is kept for a game, the game hooked again when it starts
  again, programs of the same file, the settings passed on, the clicked
  window, administrator.  The engine folder's files against ENGINE.txt
  (their kinds, the functions called, their checksums).  The text filters
  on the cases LunaTranslator and Textractor fix; the clipboard and the
  programs and windows, against stand-ins for Windows' functions; the
  WebSocket client against a WebSocket server; the menu in a real
  Chromium, light and dark.
- (New in 0.9.0) The screen read: Sluka's screen reader (ocrd.py) loading
  stand-ins for LunaTranslator's CVUtils.dll and NativeUtils.dll --
  libraries of the same functions, built for the tests -- by the same
  declarations LunaTranslator's own Python uses (until 0.12.4, a stand-in
  for LunaSubprocess64.exe's SnippingTool mode too); Google Lens against a
  stand-in web server,
  directly and through a SOCKS5 proxy (Tor's way); on a pretend screen.
  Each reader's settings as LunaTranslator gives them (4 threads on the
  CPU; either way of writing, or the one asked; pictures made bigger for
  Windows' OCR, which reads no smaller); the lines
  put in order, vertical text, furigana left out, Windows' spaces between
  Japanese words taken out; when to read (as the text changes and stands
  still, a line that comes a letter at a time, a picture read before not
  read again, every few seconds, after a click), the game behind another
  program, minimized, closed, its window made bigger; the box dragged;
  a reader that cannot start ("auto" goes to the next).  The app's side
  end to end: the Screen tab, Sluka's windows left out of the pictures
  (or stepping aside where Windows cannot), the box kept for the game and
  read again when it starts again, stopping, another reader, the
  clipboard, a screen reader that stops (started again).  The menu in a
  real Chromium, light and dark.  The doctor's lines and ocr-check.
- (New in 0.10.0) The Screen tab's keys: written and read as people write
  them, the ones that would be taken from typing refused, against a
  stand-in for Windows' hotkeys -- held while the Screen tab is chosen and
  let go when another is, a key another program has refused and said, all
  let go while one is chosen in the menu, each of the four pressed (a box
  dragged, read at once, read once, stopped and started).  The menu's key
  boxes in a real Chromium, light and dark.
- (New in 0.10.0) remove-from-pc: this copy's shortcuts, add-on and mpv
  script taken away, another copy's left.
- (New in 0.11.0) Setup's work, against a stand-in Windows (its folders,
  its list of apps, shortcuts, the app running) and the app's commands:
  installing where asked ("Program Files" refused, a folder that cannot be
  written to, a copy unpacked by hand updated where it is, which folder
  holds one); the newest extension zip in Downloads; the shortcuts as
  chosen, another copy's left alone; updating from zips -- the
  extension's, Sluka Desktop's, a setup's, neither, Linux's edition --
  with your data, the extension and config.ini kept, and 0.10.0's console
  setup taken away; all or nothing where a file is in use (each of the
  moves made to fail in turn: the folder exactly as it was); a zip that
  would write outside its folder; uninstalling, keeping your data or not,
  without Python, an older app's; the running app seen on its address.
  Then the same program built for Linux (its work without its window),
  given the real Setup: it installed the real app, whose own commands put
  the extension in and made its menu entry; updated the extension from a
  zip and itself from the Setup (your data kept, its own program put
  beside the app, byte for byte); uninstalled, kept your data, installed
  again there, uninstalled for good.  The Setup itself: a 64-bit Windows
  program with a window and no console, its icon (all nine sizes), its
  manifest (no administrator, Windows' own controls, sharp on a high-DPI
  screen) and version, and the app's files after it, exactly the zip's.
- (New in 0.11.0) The worker page's window, asked to show itself, stays
  hidden (the stand-in Windows asks a window first, as Windows does).
- (New in 0.12.0) Sluka Vision, end to end on a pretend screen: Google Lens'
  request and answer written and read by their field numbers (Chromium's
  lens_overlay protos), against a stand-in Google that reads the request
  as protocol buffers and answers a layout of paragraphs, lines and words;
  furigana left out (over a line, beside a column, tilted with its line),
  columns read right to left; the window in front read at its key, chosen
  by a click, or read again by itself once a change has settled -- not
  read again when nothing changed, nor while the change goes on, nor when
  it is turned off; the words of a changed line put away at once, all of
  them for a window made larger; the game behind another window,
  minimized, moved, closed; Google refusing, Sluka offline; another reader
  (a line each, no words).  The app's side: the tab's state, keys and
  calls, the overlay's page fed and its engine player, the floating
  subtitles put away and back.  Its window, in the stand-in Windows:
  topmost, no taskbar button, never the keyboard, kept out of pictures of
  the screen, laid over the game's inside (all but a row where that is a
  whole screen), shaped to its words, hidden and shown as the game goes
  behind and comes back, moved with it, gone with the tab.  The page in a
  real Chromium: each word's place along its line (Lens' words, or the
  letters spread), tilted lines, columns, a word over two lines, the
  underline colours by level, the card, the panel, a grade, lines put
  away, the parts of the window drawn on, a screen at 125 %.  The Game
  text menu's new tab, and the Other program tab gone.
- (New in 0.12.1) A button's animation over a line, frame after frame:
  its words stay, and go only once it stands still otherwise than it was
  read; a line lit and kept lit goes within a second and comes back dark
  again; the lines of the word pointed at do not have the window read
  again by themselves (other lines do, and so does letting go); the
  taskbar in front is never the game, nor the window chosen.  Each fails
  with 0.12.0.  Sluka's grading keys held for an open panel only while the
  game itself is in front, pressed into the page, given back as the panel
  closes; the lit level back to New and a double-click that does not undo
  itself, in Sluka Vision's page and the floating subtitles'; a line
  under the pointer kept until it leaves; the 👀 in both panels (not in
  the card).  The engine's count of a click, with Sluka 0.7.4's own
  counter (lib/lookups.js) in a real Chromium: a hover is not a lookup, a
  click is, once a minute at most, written under this device's name
  beside the others', shown from the third.  The never-shown window:
  shown without being asked, or by its style, it is hidden again; its X
  only hides it; Sluka's windows that do not show are never told to stay
  out of pictures (each fails with 0.12.0).
- (New in 0.12.2) Sluka in screenshots and recordings: the reader says
  whether it reads the game's own window or the screen -- at once when it
  has to read the screen, and only after a moment of the game's own
  picture again (each fails with 0.12.1); with the game's own window read,
  nothing of Sluka's is left out of pictures, its words' window included
  (told only while it shows); where the game's own window gives no
  picture, the screen is read, Sluka left out meanwhile, and the menu says
  why once; in again when it gives one; in the Screen tab the same for the
  floating subtitles; another tab puts every window of Sluka's back in
  pictures, whatever was left out before.
- (New in 0.12.3) What counts on Sluka's Home page.  The mpv script's
  looks at the player, in the stand-in for mpv: once a second while a file
  plays and at once at each pause, seek, end, change of sound or of file,
  none while it stays paused, a last one before it closes, and each line
  with when it starts and ends (that test fails with 0.12.2's script).
  The counting itself (web/progress.js) in Chromium, against Sluka 0.7.4's
  own lib/stats.js, lib/reading.js, lib/listening.js and
  lib/languages.js, with a stand-in for Sluka's worker that writes as its
  worker does, read back from the day records as the Home page reads
  them: a line paid for at the reader's pace and written as words read;
  the same line again the same day, in the same run or the next, counting
  nothing more; lines skipped through counting next to nothing; only the
  language's own writing counted, and nothing with "Count words read" on
  Sluka's own; the pace learned from the lines (400 a minute measured,
  460 used, with Sluka's margin) and the pages' own left alone; a line
  typed out, or read again a letter differently, being one line; Sluka
  Vision's paragraphs each once, and only while shown; a film counted by
  the Your videos rule (a seek: no more than the second it took; muted:
  nothing), its row in the Listening tab, and nothing for a film in a
  language you do not learn, or that nothing names (held time counted
  once its subtitles turn out to be Japanese); a subtitle line counted as
  subtitle words once half of it has played, and once in a file; two films
  at once counted once; half a game's time as listening, and none once
  its text is half an hour old; a write that fails offered again and
  never counted twice; a Sluka whose worker does not know the messages
  written to directly; what is owed sent as the page goes.  The engine
  whole, with Sluka's own modules and data (Spanish): answering as before,
  counting the floating subtitles', mpv's and a game's, and a worker that
  takes eight seconds a write never holding a line up.  The play
  clock: with stand-ins for the menu's state (the game in front, Sluka's
  own window, another program, not hooked, the Clipboard tab, five idle
  minutes, a key, new text, a controller -- a stick trembling at rest is
  no use of it -- the computer asleep, a box in no window), and through
  the Sluka Vision tab on its pretend screen.
- (New in 0.12.4) The law's side (test_legal.py): LICENSE.txt and its
  notices (NOTICES.txt, from 0.12.5) say what they must (Microsoft's terms
  for its runtime files, the GPL's parts needing no acceptance, Google
  Lens, the games), and every licence file they name is there, every
  program file of the engine named; each of Sluka's own files says its
  licence at its top; hookd.py and ocrd.py import nothing of the app's,
  and nothing of the app's imports them or loads LunaTranslator's
  libraries; the Snipping Tool's reader gone, a choice of it becoming an
  offline reader, and only its three copied files taken away; Google Lens'
  question put once, nothing sent to Google before the yes (Sluka Vision
  end to end, on its pretend screen), the yes kept, a no choosing an
  offline reader; ONNX Runtime's trace events turned off through its own C
  API, against the real ONNX Runtime (Linux's); a font that says
  "Microsoft supplied font ...  Any other use is prohibited", or whose
  embedding is "restricted", refused a copy, an Open Font License one
  copied as before; the add-on's licence going into Anki with it.  Setup:
  its licence agreement written from LICENSE.txt and Go's own LICENSE,
  shown by --headless license, and needed (--accept-license) to install,
  update or put in a zip; built for Windows and vetted (go vet) with its
  dark look.
- (New in 0.12.5) A game's own window that keeps an old picture
  (test_frozen_window.py), on the pretend screen: a device context that
  keeps the title menu given up at once for Windows' own drawing of the
  window, Sluka Vision then reading the game as it is, its words still in
  recordings (that test fails with 0.12.4); a window whose every picture
  is frozen read off the screen once the game has gone on a few seconds,
  said once in a message of its own and in the menu, and tried afresh
  when what is read is set again; never taken for frozen behind another
  window, in a scene that stands still, or where only Sluka's own words,
  card or panel change the screen -- a panel left open over two fifths of
  the window included; the Screen tab the same.  Setup's size: a quarter
  larger, less where that would not fit on the screen, never smaller than
  Windows' own (Go's test).  The agreement and its notices: what each
  says (the law and ARN included), the notices shown after the agreement
  by --headless license, and the old notices file taken away by an update
  from 0.12.4.
- (New in 0.13.0) Anki cards from games and films (test_cards.py,
  test_engine_anki.py, and the pages' and mpv script's own tests): the
  game's sound kept by when each piece was played, silence where nothing
  came, the last minute only; a line's clip from before it came to where
  its voice stops, over music too, or to the next line, waiting for the
  rest of the voice when picked at once; with the lines either side; the
  picture of the game's window; a hooked game's lines and Sluka Vision's
  reads kept with their game, its sound followed and let go of.  In a
  real Chromium against the extension's own modules: the panel's Anki key
  as a page has it, the sentence cut as a page cuts it, the pick with its
  form and source, the clip made by the extension's own encoder (WAV here,
  where Linux's Chromium has no AAC encoder; AAC where it has) and the
  picture its JPEG, a video chosen giving the picture; a film's clip read
  out of its file by the extension's own reader, padded as a subtitle's.
  The bar's and Sluka Vision's Anki key, by a click and by its key; mpv's,
  drawn, pressed, with the file, its sound track and the frame.
- (New in 0.16.2) A restore's write of more than 8 MB from a real page
  through the app's real server, and read back whole; failing, as users
  saw it, without the fix.
- (New in 0.16.1) The backup folder, end to end: the extension's real
  dashboard and worker served by the app's real host, its folder window
  answered with a folder standing in for G:\My Drive\Sluka -- chosen
  from Settings → Sync & backup, the phone's backup there merged in
  through the Google Drive steps, this computer's written beside it with
  the phone's words, and after a start again the folder still chosen and
  written to.  The folder's calls (test_folders.py): kept across starts,
  read and written in pieces and put in place whole, folders made and
  removed, a folder gone said to be; nothing outside it reachable (..,
  a full path, a link out of it, a folder never chosen, another site).
- (New in 0.16.0) Your own dictionaries in the panel: in the engine
  against the extension's own modules (Sluka's worker asked as a page
  asks it, Settings' place for them, its renderer's markup and each
  dictionary's own sheet, plain text for mpv, a word none has as
  before); in the bar's and Sluka Vision's pages (instead of Sluka's
  meanings, under and above them, a link opened by the engine); in mpv
  (the three places).  The kinds of file made into Yomitan dictionaries
  (test_dictfiles.py): each kind as its makers write it -- StarDict with
  and without its type sequence, 64-bit offsets, synonyms, HTML; a
  UTF-16 Lingvo file with its markup, stress marks, optional parts and
  links; JMdict, CC-CEDICT, CC-Canto, Folkets and kaikki plain and
  gzipped -- in a zip, a tar and compressed; names in an archive kept
  inside it, an archive that would fill the disk stopped, what is no
  dictionary said to be so; the dashboard's calls.  End to end, in the
  dashboard's card with the app's real converter behind it: a StarDict
  set, a Lingvo file and a gzipped CC-CEDICT each read by the
  extension's own Yomitan reader, a table and a Yomitan dictionary
  passed on as they are.
- (New in 0.16.0) The AI check: in the engine against the extension's
  own settings and providers (offered only where it is on, a key or a
  button as a page offers it, its title naming the company, F unless a
  grading key has it; the word, its sentence and its language asked of
  the worker; its answer, and what went wrong, told to the panel); in
  the bar's and Sluka Vision's pages (the key, the button, F, held in a
  game, asked once, the answer under the meanings with "Your
  question"); in mpv (the key drawn, F only while the panel is open,
  the answer, the button and a click on it).  Sluka Vision's keys
  pressed quickly: a word about a picture let go of is not taken for
  one asked for since.
- (New in 0.15.0) The game stopped where it is: the screen reader
  keeping a picture, written as it was taken, looked at in place of the
  window (the game going on behind it unread), read where its words are
  not those shown, its key reading it again, and once let go of, the
  window compared with what was read off it; in the app, both keys and
  the menu's buttons, the game paused only after its picture is kept,
  the one and then the other, Windows' stand-in for a window that does
  not answer taken for the game, a game that may not be paused frozen
  instead, every way of letting go (its key, another tab, another
  window, the game gone, the reader stopped), a card's picture, a game
  left paused let go of at the next start; on the page, the picture
  under the words at 100 % and 150 %, the window taking the pointer all
  over, the pill, a click off the words.
- (New in 0.14.2) The speaker: in the engine against the extension's own
  speaker (lib/speech.js), Google Translate's voice asked for the word
  where no cloud voice is set up, and after a cloud voice that fails,
  the panel told when it plays and when it stops; in the bar's and Sluka
  Vision's pages (where it stands, level with the word; a click and V;
  its key held in a game); in mpv (drawn with the extension's mark, lit,
  V, a word said by itself only while the video is paused).
- (New in 0.14.0) The panel's Translate and Look up keys: in the bar's
  and Sluka Vision's pages (their order, the translation shown, the menu
  with each site and its dictionary offline, what each asks the engine);
  in the engine against the extension's own modules (Translate asked as
  a page asks it, the sites as Settings lists them, the window asked for
  each); in mpv (the keys drawn with the extension's marks, the
  translation).  The windows, against the stand-in for Windows' web
  view: a site's from an engine of its own (its own data folder, a
  browser's web security, no way into the app, kept off the app's
  pages), the offline page's from the app's, each reused for the next
  word.  The offline dictionaries (test_dictionaries.py): each read from
  a file as its makers publish it, looked up, installed from a stand-in
  for its site (Wiktionary's file found on its language's page), a
  failed download leaving nothing; nothing downloaded offline; in tor
  mode, the download through a stand-in for Tor's proxy, which is given
  the site's name; the calls taking only a site or a page of the app's
  for a window.
- Everything the Tails version was tested with, again, unchanged.

Not run anywhere, because it needs Windows itself:

- Windows' web view itself: finding it, starting it, its windows.  The
  doctor tries exactly this, step by step, and says where it stops.
- Sluka.cmd, and the app carrying on without its console (pythonw).
- The window menu's text, the icon, the dark title bar, the shortcuts made
  by install-menu.
- Real named pipes; the mpv script under LuaJIT (the stand-in runs it in
  Lua 5.3).
- Reading the fonts folder and the registry; junctions for Anki; the add-on
  inside a real Anki on Windows; the font copies inside a real mpv.
- (New in 0.8.0) The real LunaHost64.dll and LunaHook in a real game.
  hookd.py calls them exactly as LunaTranslator 12.1.3.12's own Python
  does (its declarations were copied, and checked against LunaHook's C
  source), but they were never run here.  If the engine does not start,
  or a game does not connect, the menu,  .\sluka hook-check  (section 7)
  and data\logs\hookd.log say where it stops.  The real clipboard and
  Windows' list of programs.
- (New in 0.9.0) The real readers: CVUtils.dll with ONNX Runtime and the
  PP-OCRv5 model, Windows' OCR, Google Lens; the box-dragging window;
  pictures of the real screen and of a real game's window; leaving
  Sluka's windows out of them.  ocrd.py calls the libraries as
  LunaTranslator 12.1.3.12's own Python does (its declarations, checked
  against the libraries' C++ source), but they were never run here.  If
  the screen is not read: the menu (each reader says why it cannot be
  used),  .\sluka ocr-check --read  and data\logs\ocrd.log say where it
  stops.
- (New in 0.10.0) Windows' hotkeys themselves (RegisterHotKey), in a real
  game.  If a key does nothing, see "When something is wrong".
- (New in 0.12.3) Windows' own word on the last key or mouse movement
  (GetLastInputInfo) and on game controllers (XInput), in a real game; the
  numbers on the Home page in the app's own window (the day records it
  reads them from are what was checked).  If a game's minutes do not come:
  the game has to be the window in front, and its text in the language.
- (New in 0.12.4) Setup's dark look itself: its black title bar (Windows
  11 colours it as asked; Windows 10 makes it dark), its buttons, tick
  boxes and round buttons drawn in Sluka's colours, the licence page and
  its link, the progress bar; and the message box that asks about Google
  Lens, and ONNX Runtime's trace events turned off in Windows' own
  onnxruntime.dll (the same C API, by the same function's place, as was
  checked on Linux's).  If Setup looks wrong, send a screenshot.
- (New in 0.12.5) Ace Attorney itself, and Windows' own pictures of a
  real game's window (its device context, and Windows' drawing of it):
  what was checked is how Sluka chooses between them and the screen, on
  pictures made to be like theirs.  Setup at its larger size: if anything
  in it is cut off, or too large for your screen, send a screenshot.
- (New in 0.16.1) Windows' own folder window, and the GTK one on Tails:
  the tests answer it themselves.  Nor Google Drive for desktop itself:
  a folder of it is an ordinary folder to the app, and was one here.
- (New in 0.16.0) A real AI provider (nothing went over the network
  here: the answers were the worker's as Sluka's own tests have them),
  and real dictionaries of each kind: the converter was tried on small
  ones written as their formats are documented.  A StarDict or Lingvo
  dictionary that comes out wrong: send its .ifo (or the .dsl's first
  lines) and the log's lines about "a dictionary of yours".
- (New in 0.15.0) A game paused for real (Windows' own pausing of a
  program, and what a game does when it goes on -- its sound, a moment
  of it may repeat; one with an anti-cheat may refuse, or notice), the
  picture laid over a real game, and Windows' stand-in for a window that
  does not answer.
- (New in 0.14.2) The sound itself, on Windows: it plays from the app's
  hidden page (Sluka's engine).  Google Translate's voice is an address
  Google keeps for its own site, not a service it offers: it may refuse
  for a while after many words (the toast says so, and the next voice
  answers) or go away one day, as the extension's translation box's
  would.  On Tails, it needs [network] mode = tor, and the sound plays
  through WebKit.
- (New in 0.14.0) The small windows themselves (in WebView2), a real
  download from each dictionary's site (their addresses as they publish
  them today), and the sizes of Wiktionary's files: some languages' run
  to hundreds of MB (Japanese's, about 370 MB; English's, gigabytes),
  which the window says before it installs one.  kaikki.org marks those
  files as to be removed one day: when they are, Wiktionary's install
  says its site has no file, and the site itself stays in the menu,
  online.  On Tails, a site opens in Tor Browser (asked first, as any
  link is), and a dictionary is downloaded only with [network] mode =
  tor in config.ini (Tails' Sluka is offline unless told otherwise):
  then through Tor.
- (New in 0.13.0) A game's own sound from Windows (process loopback, in
  gamesound.py), and the picture of a real game's window (gamepicture.py):
  what was checked is everything they are put to.  And the extension's
  round making the card in a real Anki through AnkiConnect, which is the
  extension's own and unchanged.  If a game's card has no sound, see "When
  something is wrong".
- (New in 0.11.0) Setup's window itself: its pages, buttons and tick
  boxes, its look at your screen's scale, the windows to choose a folder
  or a file in; Windows' list of apps (the registry), Setup's own
  shortcut, finding Python as Sluka.cmd does (the py launcher, then
  Windows' list of Pythons, then the PATH), starting Sluka at the end,
  and uninstalling from a copy of itself out of the folder it takes away.
  Each is Windows' own way of doing it, called as Windows documents it,
  but none of it ran here.  If Setup's window does something wrong, a
  terminal says what its work would be:
      .\Sluka-Desktop-Setup-0.16.2.exe --headless find
- (New in 0.12.0) Sluka Vision against Google itself (its request is the
  one LunaTranslator's NativeUtils sends, and its answer was read as
  Chromium's protos define it, but neither went over the network here),
  and its window over a real game: the see-through window shaped to the
  words, the pointer over it, kept out of pictures of the screen (Windows'
  SetWindowDisplayAffinity).  If the words do not appear, or sit beside
  their text, see "When something is wrong".
- Every online feature of Sluka: where this was built there is no network.


12. Security notes
------------------

The Tails version was built around Tails' rules. This one is not, and
these are the differences that matter:

- web_security = off. An extension may read any website; a page served
  from this computer may not. So the app's web view is started with that
  rule off (--disable-web-security). It applies to the app's own web view
  only, which shows only Sluka's pages; websites you click open in your
  own browser (the Look up key's sites: below). With "on", what Sluka
  fetches from other sites fails.
- The app's pages are served at http://127.0.0.1:47821, to this computer
  only. Requests coming from a website are refused, but any program
  running on this PC as you can reach that address -- which is how other
  programs put text into the floating subtitles.
- Sluka Vision's "Pause the game" pauses one program only -- the one
  whose window it reads -- only when its key (or the tab's button) is
  pressed, with no more of a right over it than pausing and letting go
  takes, and lets it go as said above.  Pausing puts nothing into the
  game and changes nothing in it: its threads are only held, and let go
  of.
- The Look up key's dictionary sites: in a small window of Sluka's, from
  a web view of their own, which is a browser's -- web security on,
  their cookies and the like in data\webview2-dictionaries, none of the
  app's tokens (the app refuses whatever a site asks of it, as above,
  and the window will not go to the app's pages), [network] mode as the
  app's.  An offline dictionary is downloaded only when you press
  Install, from its makers' own site (JMdict's has plain http only), and
  read as data: what you look up in it stays on this PC.
- The backup folder: the app reaches only the folder chosen in the
  folder window (data\folders.json keeps which, by a random number), and
  only the files and folders inside it; a path out of it, a link out of
  it, or another site's page is refused.  What Sluka writes there is
  what it writes in Chrome: its backup, and the books and films Settings
  → Sync & backup says may travel.
- The AI check sends the word, and its sentence where Settings → AI
  check says so, to the company that Settings names -- only when its key
  or button is pressed -- from the extension's own worker, with the key
  you gave it there; the app neither sees nor keeps the key.
- A dictionary file of yours is read on this PC as data only: names in
  an archive are not followed out of it, nothing in one is run, its
  definitions keep only what the extension's panel draws (links only to
  the web), and what is unpacked is held to 6 GB.  Nothing of it is
  sent anywhere.
- No debugging port is opened any more: the page of Sluka's worker is one
  of the app's own, out of sight, as on Tails.
- Game text: Sluka's engine puts a library into the game you choose, and
  reads the text that goes through it; that is all it does, and only to
  the game you hook (it is let go when you say so, or when the app ends).
  It is LunaHook, open source: the files of LunaTranslator 12.1.3.12 as
  their author signed them.  engine\ENGINE.txt lists them with their
  checksums, and engine\source holds their source code.  Only the app's
  own pages can tell it what to hook: neither a website nor another
  program can.
- The screen read: only the box you dragged is looked at, and only while
  the Screen tab is chosen; its pictures stay on this PC, unless you
  choose Google Lens, which sends each of them to Google.  While the
  screen is read, Sluka's own windows are left out of every picture of
  the screen -- screenshots and recordings included; while the game's own
  window is read, they are not.
- Sluka Vision: only the window you chose (or the one in front when you
  press its key) is looked at, and only while the Sluka Vision tab is
  chosen.  With Google Lens -- as it comes -- each read sends a picture of
  that whole window to Google; choose an offline reader in the tab to keep
  them on this PC.  Its own window, and Sluka's others meanwhile, are left
  out of every picture of the screen.
- Two tests in Sluka's code that ask "am I running as an extension?" by
  looking at the page's address are answered "yes" as the files are sent
  to the web view (http is accepted where chrome-extension is).
  Nothing in the extension folder is changed, and nothing about Sluka's
  licence or its free allowance is touched.


13. When something is wrong
---------------------------

    .\sluka doctor            what is there and what is missing; it also
                              tries Windows' web view with a page of its own
    .\sluka webview-check     that try, step by step
    .\sluka --foreground -v   the app in the terminal, saying what it does
    data\logs\sluka-desktop.log
    data\logs\crash.log       if the app vanished: where it happened

- "Python was not found": step 1 of Installing.
- "Windows' own web view was not found": Windows Update puts it in; its
  installer (the "Evergreen Bootstrapper") is also at
  https://developer.microsoft.com/microsoft-edge/webview2/ .  Meanwhile a
  browser can show the windows: [app] shell = browser in config.ini.
- No window: the log's last lines say why. If another program has port
  47821, the app says so; see Settings.
- mpv shows no Sluka: is the app running? Was mpv opened after it? With
  the video open, .\sluka doctor says whether the player answers the app;
  one that does not has an older script in it: close it, open the video
  again. If mpv is a portable one: .\sluka install-mpv FOLDER. Then
  script.log (section 4).
- No Anki key in a panel: Settings → Anki's word panel button is off
  for that language (it shows only on a panel opened with a click).  A
  card that never comes: Anki and AnkiConnect have to be open, as for the
  extension's own cards.
- A game's card without its sound: Windows older than 10 version 2004
  gives no program's sound alone (the game text menu says so once); or
  the word was picked on a line that came before the game was hooked, or
  before Sluka Vision read its window.  data\logs\sluka-desktop.log says
  "the sound of process ... is being kept" while it is.
- A game that stays paused: press Sluka Vision's pause key again
  (Alt+P), or choose another tab.  Sluka gone meanwhile: start it again,
  and the game goes on; or in Resource Monitor (resmon), on the CPU tab,
  right click the game, Resume process.
- "Windows does not let Sluka pause" a game: it runs as administrator
  (run Sluka as administrator too), or an anti-cheat guards it -- use
  Freeze the picture (Alt+F) for it.
- The backup folder asks to be reconnected: the folder chosen is not
  there now -- Google Drive for desktop not running or signed out, or
  the drive under another letter.  Start Drive (or put the drive back)
  and press Reconnect; or choose the folder again.  No other device's
  words in it: Drive keeps files online until they are needed, so this
  computer has to be online to fetch them.
- No ✦ in a panel: Settings → AI check is off (it is off as it comes).
  A key or a button that answers with an error: the error is the
  extension's, as its own panel would say it (a key missing, a quota).
  F does nothing in mpv: it is the panel's only while it is open.
- Your own dictionaries not in a panel: they are the language's that
  Settings → Languages had chosen when you added them; a word none of
  them has shows Sluka's meanings.  A file that "Sluka Desktop does not
  know": see the list in section 5; a StarDict dictionary needs its
  .ifo, .idx and .dict picked together (or the archive they came in).
- No Look up key in a panel: Settings → Dictionary links has no site on
  for that language (the extension's own list, as its panel shows it).
- A dictionary that will not install: its window says why.  "Set to work
  offline": config.ini's [network] mode (section 8).  "Its site did not
  answer" or a failed download: the site is down or has moved its file;
  try again later (the site stays in the menu, online, meanwhile).
  data\logs\sluka-desktop.log names the address it tried.  A dictionary
  installed is a file in data\dictionaries; Remove, in its window, takes
  it away.
- A film's card without its sound: its sound track is one Sluka cannot
  read in a file (AC-3, DTS), or the file is not on this computer (a
  stream): the card has the frame and the sentence.
- Anki shows no Sluka: restart Anki after install-anki (and after an
  update of the app); app running? Tools > Add-ons must list "Sluka
  Desktop". With both open, .\sluka doctor says whether Anki answers the
  app. The add-on's own notes: user_files\log.txt in its folder
  (%APPDATA%\Anki2\addons21\sluka_desktop).
- A Windows user name with letters outside English: mpv is still found
  (by its pipe), but the script may be unable to write script.log.
- The floating subtitles show a black ground round the box, or nothing:
  say which, with the log's lines about "floating subtitles" and your
  Windows version.  Meanwhile: the window menu takes the clicks back, the
  button puts them away.
- The screen: each reader says in the menu why it cannot be used here, and
  so does  .\sluka doctor.  Sluka's own: "Microsoft's C++ runtime 14.40 or
  later" -- a newer Python (python.org's newest) has it; meanwhile another
  reader reads.  Windows': "no OCR for ja" -- add the language's OCR (the
  Screen part of section 7).  Nothing read: "Read now", then "What the
  screen reader says"; a box tight round the text reads best.  Send what
  .\sluka ocr-check --read  prints, with data\logs\ocrd.log.
- The screen's keys: they work while the Screen tab is the one chosen.  A
  key the menu shows in red could not be had (another program has it):
  choose another.  One that shows as held but does nothing in the game:
  say which key, which game, and whether the game runs as administrator,
  with the lines of data\logs\sluka-desktop.log that say "key:".
- Sluka Vision: no words over the game -- play it in a window or a
  borderless window (nothing can be laid over exclusive full screen), and
  see that "Sluka Vision · reading..." shows at its top right when you
  press Alt+S.  Alt+S does nothing: YomiNinja (or another program) may
  have it -- the tab shows the key in red; close it, or choose another
  key.  "Google Lens answered 429": Google asks for fewer reads; wait a
  minute, or untick "Read again by itself".  Words beside their text, or
  in another place: say which game, its window's size and your screen's
  scale (125 %, 150 %), with a screenshot, and data\logs\ocrd-vision.log.
  Sluka's words missing from your screenshots and recordings: choose "The
  game's own window" in Sluka Vision settings (and in the Screen tab's
  Reading settings, for the floating subtitles) -- the menu says when a
  game's own window cannot be read as it shows.  The same old words over
  the game however often it is read again (its title menu, long after):
  until 0.12.5, some games' own windows gave Sluka an old picture.  Where
  0.12.5 still reads one wrong, read the screen ("What Sluka Vision
  reads"), and say which game, with data\logs\ocrd-vision.log (its lines
  "window:" say how the window was taken).  The message "reading the
  screen" (once a game): Sluka had to read the screen for it, as it says;
  the tab chosen again tries the game's own window afresh.  Read back, or
  underlines in screenshots while the screen is read: your Windows is
  older than Windows 10 2004 -- choose "The game's own window" there too.
  A game that stutters, or reads worse, from its own window: read the
  screen.
- Setup: Windows will not start it ("Windows protected your PC"): "More
  info", then "Run anyway" -- it is not signed.  Windows Security takes it
  away: the zip still installs as before (section 2, without the setup).
  Setup says it stopped on an error: send what it says.  It does not find
  your Sluka Desktop: "Another folder...".  In a terminal,
      .\Sluka-Desktop-Setup-0.16.2.exe --headless find
  says which Python and which Sluka Desktops it finds.
- Reading or Listening on the Home page does not go up: an mpv opened
  before the update counts nothing (open the video again); for a film,
  data\logs\sluka-desktop.log has a line saying how many minutes counted,
  or why they did not ("mpv: ... not counted: ...") -- a film whose
  tracks are not marked with a language, whose subtitles are off or in
  another language and whose title says nothing counts nothing: turn on
  subtitles in your language.  Game text: it counts at your own pace, so a
  line skipped through counts next to nothing; nothing counts with
  Settings > Reading > "Count words read" set to Sluka's own reader and
  books.  A game's listening: the game has to be in front, its text in
  your language, and the floating subtitles on (or Sluka Vision's words
  over it).  Words are written every half minute, minutes every minute.
- Game text: the menu says what keeps the engine from starting or a game
  from being hooked (a file missing, administrator, a game that does not
  connect), and so does  .\sluka doctor.  A game that shows no thread with
  its lines: advance its text, then look under "What the engine says";
  tick "Read Windows' text functions too"; try a hook code.  Send what
  .\sluka hook-check PID  prints while you advance the game's text, with
  data\logs\hookd.log and the game's name.

If a part fails, the lines to send back are the output of .\sluka doctor,
the end of data\logs\sluka-desktop.log, data\logs\crash.log if it has
more than its first line (and script.log for mpv, hookd.log or ocrd.log for
game text).


14. Removing
------------

Settings > Apps > Installed apps > Sluka Desktop > Uninstall -- or "Sluka
Desktop Setup" in the Start menu, "Uninstall Sluka Desktop".  It asks
whether to keep your words, books and settings (the data folder and
config.ini stay in the app's folder), then takes away
the app's folder, its shortcuts, its add-on in Anki, its script for mpv
and the font copies beside it, %LOCALAPPDATA%\sluka-desktop, and its line
in Windows' list of apps.  What another copy of the app put there is left
to that copy.

By hand, or for a copy the setup never saw: in a terminal in its folder,

    .\sluka remove-from-pc

then delete the folder (Sluka's engine, in its engine folder, goes with
it), and %LOCALAPPDATA%\sluka-desktop.  remove-from-pc takes away what the
uninstall does outside the folder: the shortcuts, the add-on in Anki
(%APPDATA%\Anki2\addons21\sluka_desktop, and wherever install-anki put
it), sluka.lua in the scripts folders of section 4 and the Sluka-*.ttf
files in the fonts folders beside them.


15. Licences and the law
------------------------

Sluka Desktop is part of Sluka, and is used under Sluka's terms
(https://sluka.app/terms), as the extension is: LICENSE.txt, in the app's
folder, is its licence agreement -- the one Setup shows first.  In short:

- Parts of it are free software, under the GNU General Public License:
  app\sluka_desktop\hookd.py and ocrd.py (version 3, as LunaTranslator,
  whose code they use, is), mpv\sluka.lua and the Anki add-on (version 3
  or later).  Each says so at its top; LICENSES\GPL-3.0.txt is the
  licence.  They are programs and scripts of their own: Sluka's own
  program runs them and speaks with them in lines of JSON, and never
  loads them, nor LunaTranslator's libraries, into itself.
- The engine folder is LunaTranslator 12.1.3.12's, unchanged, under the
  GNU GPL version 3, with its complete source code in engine\source and
  at https://github.com/HIllya51/LunaTranslator/tree/v12.1.3.12 .
- NOTICES.txt, beside it, has the rest, which the agreement points to:
  what Sluka Desktop does and sends; its free parts; Microsoft's terms
  for its C++ runtime files in the engine folders (3: part of the
  agreement); and file by file whose software is in it, under which
  licence, and where its source code is.  The licences are in LICENSES
  and engine\LICENSES.  Nothing in Sluka's terms limits what those
  licences let you do with those parts.
- The law: Swedish, as for the extension (Sluka is made in Gothenburg,
  Sweden).  A consumer keeps the protection of the mandatory rules of the
  country where they live, and may take a dispute to Allmänna
  reklamationsnämnden (ARN), Sweden's National Board for Consumer
  Disputes.
- What leaves your PC: nothing by Sluka Desktop itself.  Google Lens
  sends Google each picture it reads, once you have said yes to it;
  Sluka's own OCR has ONNX Runtime's trace events for Microsoft turned
  off; the extension's online features are the extension's.
- Game text puts a hook into a game: some games forbid that in their own
  terms (online games, anti-cheat software above all).  Use it only with
  games that allow it.
- Left out, for the law's sake: the Snipping Tool's OCR (Microsoft's, in
  its Snipping Tool app); changed copies of fonts whose licence forbids
  them (section 4).

"Licences and notices", in each window's menu (the icon at the top left,
or Alt+Space), opens LICENSE.txt; About says what the app is used under,
and whether Google Lens has had its yes (and can have the question put
again).  Setup in a terminal shows its agreement, and the notices after
it, with

    .\Sluka-Desktop-Setup-0.16.2.exe --headless license

and installs or updates only when told it was accepted:

    .\Sluka-Desktop-Setup-0.16.2.exe --headless install --accept-license
