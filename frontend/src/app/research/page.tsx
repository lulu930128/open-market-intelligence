import ResearchCandidates from "@/components/research/ResearchCandidates";

export default async function ResearchPage({ searchParams }: {
  searchParams: Promise<{ market?: string; proposal_id?: string }>;
}) {
  const params = await searchParams;
  const cutoff = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date()).replace(" ", "T");
  return <ResearchCandidates initialMarket={params.market === "US" ? "US" : "TW"}
    initialSelected={params.proposal_id ?? null} initialCutoff={cutoff} />;
}
