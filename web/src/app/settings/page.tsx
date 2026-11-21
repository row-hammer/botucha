"use client";

import { ConfigForm } from "@/components/config-form";
import { PageHeader } from "@/components/page-header";
import { PersonaEditor } from "@/components/persona-editor";
import { useT } from "@/lib/i18n";

export default function SettingsPage() {
  const t = useT();
  return (
    <>
      <PageHeader title={t("nav.settings")} />
      <div className="grid gap-4 p-4 xl:grid-cols-[3fr_2fr]">
        <PersonaEditor />
        <ConfigForm />
      </div>
    </>
  );
}
