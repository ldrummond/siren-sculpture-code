# Audio Files

Place the main ambient audio file here:

```text
/opt/sculpture/siren-app/assets/audio/somefile.wav
```

The default config expects:

```text
/opt/sculpture/siren-app/assets/audio/somefile.wav
```

Large audio files are not committed to Git by default.

Options:

1. Copy the audio file manually with `scp` or a USB drive.
2. Use Git LFS if versioning audio is desired.
3. Attach audio files to GitHub Releases and download them during deployment.

After copying the audio file, test with:

```bash
/opt/sculpture/siren-app/scripts/test-audio.sh
```
