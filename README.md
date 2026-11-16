# SINCA Game Launcher

## Set up Supabase

1. Create a Supabase project.
2. In the Supabase SQL Editor, run the contents of `supabase-schema.sql`. The table uses row-level security so each signed-in user can access only their own save.
3. In Supabase's **Data API** settings, make sure `public.game_progress` is exposed.
4. In `supabase-config.js`, replace the placeholders with your Supabase project URL and **publishable** key (or legacy `anon` key). Never put a `service_role` or secret key in this file.
5. In Supabase, open **Authentication → URL Configuration**:
   - Set **Site URL** to your Netlify site URL, such as `https://your-site.netlify.app`.
   - Add that same URL as a redirect URL. Add `http://localhost:8000` as a redirect URL too if you want to test locally.
6. Keep email confirmation enabled if you want users to verify their email. New users will need to confirm before signing in.

## Deploy to Netlify

1. Put this project in a Git repository and push it to GitHub.
2. In Netlify, choose **Add new site → Import an existing project** and connect the GitHub repository.
3. Leave the build command empty. `netlify.toml` sets the publish directory to the project root.
4. Deploy, then use the assigned `https://...netlify.app` URL. Do not open `index.html` as a local file.
5. If you change the Supabase URL or key in `supabase-config.js`, commit and push the change to trigger a new deploy.

The browser uses Supabase Auth for email/password accounts and the `game_progress` table for saves. The project URL and publishable/anon key are intended for browser use; the SQL row-level security policies are essential. Do not disable them.

The old `server.py` and its local SQLite accounts are not used by the Netlify version. Existing local accounts and saves are not automatically transferred; users will need to create new accounts on the hosted site.

## Test locally

After configuring Supabase and adding `http://localhost:8000` as an allowed redirect URL, run:

```powershell
python -m http.server 8000
```

Then open `http://localhost:8000`. Keep the terminal open while testing.
