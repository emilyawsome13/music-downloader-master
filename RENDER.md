# Deploy On Render

This project is set up to run as a Render web service.

## GitHub Desktop

1. Open GitHub Desktop.
2. Choose `File` -> `New repository`.
3. Select this folder:
   `C:\Users\autom\Downloads\spotify-downloader-master\spotify-downloader-master`
4. Create the repository, then publish it to GitHub.

## Render

1. In Render, create a new Web Service from your GitHub repo.
2. Render will detect [render.yaml](./render.yaml).
3. Add these secret environment variables in Render:
   - `SPOTDL_CLIENT_ID`
   - `SPOTDL_CLIENT_SECRET`
4. Deploy the service.

## Notes

- The app starts with:
  `uvicorn spotdl.render_app:app --host 0.0.0.0 --port $PORT`
- FFmpeg is downloaded during the Render build step.
- Runtime data is stored under `SPOTDL_DATA_DIR`.
- By default, the web dashboard keeps downloads in session folders and sends finished files or ZIPs back to the device using the site.
- If you want server-side files to survive restarts, point `SPOTDL_DATA_DIR` to a persistent disk mount in Render.
