# Case 4 Web App

Next.js App Router, TypeScript, Tailwind CSS, and the official Supabase JavaScript
and SSR libraries. The Python starter and CSV files remain in the parent folder.

## Run Locally

Use Node.js 22.13 or newer (Node 22 LTS recommended). From the Case_4 folder:

```powershell
cd web
npm install
npm run dev
```

Open http://localhost:3000, or the URL printed by Next.js if that port is busy.
The app runs without Supabase credentials and reports "Not configured".

## Connect Supabase

1. Create or select a project at https://supabase.com/dashboard.
2. Open the project's Connect dialog and choose Next.js.
3. Fill in the existing `.env.local` file with your project URL and publishable key:

```dotenv
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=your-publishable-key
```

4. Restart the development server after changing environment variables.

`.env.local` is ignored by Git; `.env.example` is the tracked template.
Never put a Supabase secret or service-role key in a `NEXT_PUBLIC_*` variable.
For deployment, set these two variables in your hosting provider's environment.

The configuration label checks only whether environment variables are present;
it does not test database connectivity. No hosted project, tables, policies,
login screens, or CSV imports have been created by this setup.

## Supabase Clients

- Client Components: import `createClient` from `@/lib/supabase/client`.
- Server Components, Server Actions, and Route Handlers: import `createClient`
	from `@/lib/supabase/server` and call `await createClient()`.
- `src/proxy.ts` refreshes auth sessions and preserves cookies and cache headers.
	It bypasses Supabase when credentials are absent. The server helper ignores
	cookie-write errors in read-only Server Components because the proxy performs
	refreshes before rendering.

The proxy is not an authorization gate. Before serving private data, verify
identity with `supabase.auth.getClaims()` and enforce database access with Row
Level Security policies. Do not trust `getSession()` for server authorization.

## Checks

```powershell
npm run lint
npm run typecheck
npm run build
```

Production startup: `npm run start` after a successful build.

References: [Next.js](https://nextjs.org/docs) and
[Supabase SSR](https://supabase.com/docs/guides/auth/server-side/nextjs).
