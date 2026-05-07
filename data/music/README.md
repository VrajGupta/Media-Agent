# Background music pool (user-curated)

Drop royalty-free trendy tracks here as `.mp3`, `.m4a`, `.wav`, `.flac`, or
`.ogg`. The editor (Pivot.3) picks one deterministically per clip via
`sha1(clip_id) % len(tracks)` — same clip → same track across reruns. Tracks
shorter than the rendered clip are looped; tracks longer are trimmed.

## Sources to use (safe — no copyright strikes)

- **YouTube Audio Library** — https://www.youtube.com/audiolibrary (Creator Studio → Audio Library). All tracks free for any use, even commercial. Filter by genre to find phonk / lo-fi / trap.
- **Pixabay Music** — https://pixabay.com/music (CC0 / Pixabay license).
- **FreePD** — https://freepd.com (public domain).
- **Bensound** — https://www.bensound.com (free with attribution; check the channel description templating).

## Sources to avoid

- Spotify / Apple Music rips — copyrighted.
- Anything labelled "free download" without an explicit license — assume copyrighted.
- Popular phonk producers' tracks unless the artist explicitly grants Shorts use (Content ID will catch them).

## Volume

Tracks ship at varying loudness. The editor applies a flat
`volume=<music_volume_db>dB` reduction (default `-15` in `config.yaml`)
relative to the source level. If your tracks sound too loud or too quiet
under the dialogue, tune `music_volume_db` in `config.yaml`:

- `-10` → music more present
- `-15` → default (atmospheric bed, dialogue clearly on top)
- `-20` → music almost subliminal

## Disabling music entirely

Set `music_enabled: false` in `config.yaml`. The editor falls back to a
dialogue-only audio chain (still with reverb if `dialogue_reverb_enabled`).

## What's in this directory

This directory is committed empty (`.gitignore` excludes the audio files,
keeps the directory and this README). Audio files in `data/music/` are NOT
tracked by git — they're user-curated and stay on your machine.
