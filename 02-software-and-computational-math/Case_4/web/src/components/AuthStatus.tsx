import Link from "next/link";
import { isSupabaseConfigured } from "@/lib/supabase/config";
import { createClient } from "@/lib/supabase/server";
import { signOutAction } from "@/lib/supabase/actions";

export default async function AuthStatus() {
  if (!isSupabaseConfigured()) {
    return <p className="text-xs text-zinc-400">Supabase not configured</p>;
  }

  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  const email = data?.claims?.email;

  if (!email) {
    return (
      <div className="flex items-center gap-3 text-sm">
        <Link href="/login" className="text-zinc-600 hover:text-zinc-900">
          Sign in
        </Link>
        <Link
          href="/signup"
          className="rounded-md bg-zinc-900 px-3 py-1.5 font-medium text-white hover:bg-zinc-700"
        >
          Sign up
        </Link>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="hidden text-zinc-600 sm:inline">{email}</span>
      <form action={signOutAction}>
        <button
          type="submit"
          className="rounded-md border border-zinc-300 px-3 py-1.5 font-medium text-zinc-700 hover:bg-zinc-100"
        >
          Sign out
        </button>
      </form>
    </div>
  );
}
