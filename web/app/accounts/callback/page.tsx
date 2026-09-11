import { Suspense } from "react";
import { AccountsCallback } from "@/components/accounts/accounts-callback";

export default function AccountsCallbackPage() {
  return (
    <Suspense fallback={<p className="text-sm text-zinc-500">Completing connection…</p>}>
      <AccountsCallback />
    </Suspense>
  );
}
