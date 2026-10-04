import Link from "next/link";

export default async function AuthErrorPage(props: PageProps<"/auth/error">) {
  const searchParams = await props.searchParams;
  const error =
    typeof searchParams.error === "string"
      ? searchParams.error
      : "An authentication error occurred.";

  return (
    <main className="flex flex-1 items-center justify-center bg-zinc-50 px-6 py-16">
      <div className="w-full max-w-sm rounded-xl border border-zinc-200 bg-white p-8 text-center shadow-sm">
        <h1 className="text-xl font-semibold text-zinc-900">Something went wrong</h1>
        <p className="mt-2 text-sm text-red-700">{error}</p>
        <Link
          href="/login"
          className="mt-6 inline-block rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700"
        >
          Back to sign in
        </Link>
      </div>
    </main>
  );
}
