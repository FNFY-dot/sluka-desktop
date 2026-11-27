**read_every_card** (true or false): Sluka reads a page when it is in the language
you are learning, and tells that from the page's text. A card is often a word or
two, too little to tell by. With `true`, Sluka is turned on for every card, as if
you had chosen "Turn Sluka on here" from its menu in a browser. With `false`, it
starts only once it has seen enough of the language.

**grade_keys** (true or false): the keys 1 to 4 answer a card in Anki and set a
word's level in Sluka. With `true`, they go to Sluka while a word's panel is open
(you clicked a word), and to Anki at every other moment. With `false`, they are
always Anki's; a word's level is then set with the mouse, in Sluka's panel.

**grade_keys_on_hover** (true or false): with `true`, 1 to 4 also go to Sluka
while the pointer rests on a word, as they do on a web page. Off from the start,
because a pointer left lying on a card would then take the key you meant to
answer the card with.

Changes take effect the next time you start reviewing.

This add-on belongs to Sluka Desktop and is kept up to date by it
(`./sluka install-anki`). It does nothing while Sluka Desktop is not running.
