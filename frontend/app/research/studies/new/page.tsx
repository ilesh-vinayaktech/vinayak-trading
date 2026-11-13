"use client";

import { useQuery } from "@tanstack/react-query";
import { Suspense } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { StudyForm } from "@/components/studies/StudyForm";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { api } from "@/lib/api/client";

export default function NewStudyPage() {
  const q = useQuery({ queryKey: ["study-options"], queryFn: api.studyOptions });
  return (
    <div className="space-y-6">
      <PageHeader title="New backtest study" breadcrumbs={[{ label: "Backtest studies", href: "/research/studies" }, { label: "New" }]}
        subtitle="Every choice is yours. Once registered, the study is locked: to change anything you register a new one, and the trial count goes up." />
      {q.isError ? <Alert tone="error" title="Could not load the choices">Try again in a moment.</Alert> : null}
      {q.isLoading ? <div role="status" aria-label="Loading the choices"><Skeleton className="h-64 w-full" /></div> : null}
      {q.data && !q.data.frozen_through ? <Alert tone="warn" title="No frozen price history">Freeze the price history first; a study is pinned to it.</Alert> : null}
      {q.data ? <Suspense><StudyForm options={q.data} /></Suspense> : null}
    </div>
  );
}
