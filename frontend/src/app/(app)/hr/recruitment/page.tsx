"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import Modal from "@/components/Modal";
import { HrHeader, LoadState, MetricGrid, useHrT } from "@/components/hr/HrUi";
import { api, fetcher } from "@/lib/api";

type Position = { id: number; name: string };
type Department = { id: number; name: string };

type Candidate = {
  id: number;
  position_id: number | null;
  department_id: number | null;
  full_name: string;
  first_name: string | null;
  last_name: string | null;
  middle_name: string | null;
  date_of_birth: string | null;
  gender: string | null;
  nationality: string | null;
  country: string | null;
  region: string | null;
  district: string | null;
  address: string | null;
  passport_number: string | null;
  passport_issued_by: string | null;
  passport_issue_date: string | null;
  passport_expiry_date: string | null;
  pinfl: string | null;
  phone: string | null;
  email: string | null;
  source: string | null;
  stage: string;
  applied_on: string | null;
  interview_at: string | null;
  notes: string | null;
};

type CandidateForm = {
  position_id: string;
  department_id: string;
  first_name: string;
  last_name: string;
  middle_name: string;
  date_of_birth: string;
  gender: string;
  nationality: string;
  country: string;
  region: string;
  district: string;
  address: string;
  passport_number: string;
  passport_issued_by: string;
  passport_issue_date: string;
  passport_expiry_date: string;
  pinfl: string;
  phone: string;
  email: string;
  source: string;
  stage: string;
  applied_on: string;
  interview_at: string;
  notes: string;
};

const STAGES = ["applied", "screening", "interview", "offer", "hired", "rejected"];

function emptyCandidateForm(): CandidateForm {
  return {
    position_id: "",
    department_id: "",
    first_name: "",
    last_name: "",
    middle_name: "",
    date_of_birth: "",
    gender: "",
    nationality: "Uzbekistan",
    country: "Uzbekistan",
    region: "",
    district: "",
    address: "",
    passport_number: "",
    passport_issued_by: "",
    passport_issue_date: "",
    passport_expiry_date: "",
    pinfl: "",
    phone: "",
    email: "",
    source: "",
    stage: "applied",
    applied_on: new Date().toISOString().slice(0, 10),
    interview_at: "",
    notes: "",
  };
}

function candidateToForm(candidate?: Candidate): CandidateForm {
  if (!candidate) return emptyCandidateForm();
  const nameParts = candidate.full_name.trim().split(/\s+/);
  return {
    ...emptyCandidateForm(),
    position_id: candidate.position_id ? String(candidate.position_id) : "",
    department_id: candidate.department_id ? String(candidate.department_id) : "",
    first_name: candidate.first_name || nameParts[1] || nameParts[0] || "",
    last_name: candidate.last_name || (nameParts.length > 1 ? nameParts[0] : ""),
    middle_name: candidate.middle_name || nameParts.slice(2).join(" "),
    date_of_birth: candidate.date_of_birth || "",
    gender: candidate.gender || "",
    nationality: candidate.nationality || "",
    country: candidate.country || "",
    region: candidate.region || "",
    district: candidate.district || "",
    address: candidate.address || "",
    passport_number: candidate.passport_number || "",
    passport_issued_by: candidate.passport_issued_by || "",
    passport_issue_date: candidate.passport_issue_date || "",
    passport_expiry_date: candidate.passport_expiry_date || "",
    pinfl: candidate.pinfl || "",
    phone: candidate.phone || "",
    email: candidate.email || "",
    source: candidate.source || "",
    stage: candidate.stage,
    applied_on: candidate.applied_on || "",
    interview_at: candidate.interview_at ? candidate.interview_at.slice(0, 16) : "",
    notes: candidate.notes || "",
  };
}

function candidatePayload(form: CandidateForm, stage = form.stage) {
  return {
    position_id: form.position_id ? Number(form.position_id) : null,
    department_id: form.department_id ? Number(form.department_id) : null,
    full_name: [form.last_name, form.first_name, form.middle_name].map((part) => part.trim()).filter(Boolean).join(" "),
    first_name: form.first_name.trim() || null,
    last_name: form.last_name.trim() || null,
    middle_name: form.middle_name.trim() || null,
    date_of_birth: form.date_of_birth.trim() || null,
    gender: form.gender.trim() || null,
    nationality: form.nationality.trim() || null,
    country: form.country.trim() || null,
    region: form.region.trim() || null,
    district: form.district.trim() || null,
    address: form.address.trim() || null,
    passport_number: form.passport_number.trim() || null,
    passport_issued_by: form.passport_issued_by.trim() || null,
    passport_issue_date: form.passport_issue_date.trim() || null,
    passport_expiry_date: form.passport_expiry_date.trim() || null,
    pinfl: form.pinfl.trim() || null,
    phone: form.phone.trim() || null,
    email: form.email.trim() || null,
    source: form.source.trim() || null,
    stage,
    applied_on: form.applied_on.trim() || null,
    interview_at: form.interview_at ? new Date(form.interview_at).toISOString() : null,
    notes: form.notes.trim() || null,
  };
}

export default function RecruitmentPage() {
  const hrT = useHrT();
  const { data, error, isLoading, mutate } = useSWR<Candidate[]>("/api/hr/recruitment", fetcher);
  const { data: positions } = useSWR<Position[]>("/api/hr/positions", fetcher);
  const { data: departments } = useSWR<Department[]>("/api/departments", fetcher);
  const [editing, setEditing] = useState<Candidate | "new" | null>(null);
  const [form, setForm] = useState<CandidateForm>(emptyCandidateForm);
  const [search, setSearch] = useState("");
  const [stageFilter, setStageFilter] = useState("");
  const [positionFilter, setPositionFilter] = useState("");
  const [message, setMessage] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const filteredCandidates = useMemo(() => (data || []).filter((candidate) => (
    `${candidate.full_name} ${candidate.phone || ""} ${candidate.pinfl || ""} ${candidate.passport_number || ""}`
      .toLowerCase()
      .includes(search.toLowerCase())
    && (!stageFilter || candidate.stage === stageFilter)
    && (!positionFilter || String(candidate.position_id || "") === positionFilter)
  )), [data, positionFilter, search, stageFilter]);

  function openCandidate(candidate?: Candidate) {
    setEditing(candidate || "new");
    setForm(candidateToForm(candidate));
    setMessage("");
  }

  async function saveCandidate(event: React.FormEvent) {
    event.preventDefault();
    setIsSaving(true);
    setMessage("");
    try {
      if (editing === "new") {
        await api.post("/api/hr/recruitment", candidatePayload(form));
      } else if (editing) {
        await api.patch(`/api/hr/recruitment/${editing.id}`, candidatePayload(form));
      }
      await mutate();
      setEditing(null);
    } catch (err: unknown) {
      setMessage(String((err as Error)?.message || err));
    } finally {
      setIsSaving(false);
    }
  }

  async function moveCandidate(candidate: Candidate, stage: string) {
    await api.patch(`/api/hr/recruitment/${candidate.id}`, candidatePayload(candidateToForm(candidate), stage));
    await mutate();
  }

  return (
    <div>
      <HrHeader
        title={hrT("Recruitment")}
        subtitle={hrT("Candidate profiles and hiring workflow for approved staffing positions.")}
        actions={<button type="button" className="btn btn-primary" onClick={() => openCandidate()}>{hrT("Add candidate")}</button>}
      />
      <MetricGrid items={[
        { label: hrT("Open candidates"), value: data?.filter((row) => !["hired", "rejected"].includes(row.stage)).length ?? "—" },
        { label: hrT("Interviews"), value: data?.filter((row) => row.stage === "interview").length ?? "—" },
        { label: hrT("Offers"), value: data?.filter((row) => row.stage === "offer").length ?? "—" },
        { label: hrT("Hired"), value: data?.filter((row) => row.stage === "hired").length ?? "—" },
      ]} />

      <div className="card mb-4 grid gap-3 p-4 lg:grid-cols-[1fr_220px_260px]">
        <input className="input" placeholder={hrT("Search name, phone, PINFL or passport")} value={search} onChange={(event) => setSearch(event.target.value)} />
        <select className="input" value={stageFilter} onChange={(event) => setStageFilter(event.target.value)}>
          <option value="">{hrT("All stages")}</option>
          {STAGES.map((stage) => <option key={stage} value={stage}>{hrT(stage)}</option>)}
        </select>
        <select className="input" value={positionFilter} onChange={(event) => setPositionFilter(event.target.value)}>
          <option value="">{hrT("All positions")}</option>
          {positions?.map((position) => <option key={position.id} value={position.id}>{position.name}</option>)}
        </select>
      </div>

      <LoadState loading={isLoading} error={error} empty={!isLoading && !filteredCandidates.length}>
        <div className="grid gap-4 xl:grid-cols-3">
          {STAGES.map((stage) => (
            <div className="card p-4" key={stage}>
              <h2 className="mb-3 text-sm font-semibold">
                {hrT(stage)} <span className="text-[#8a8472]">({filteredCandidates.filter((row) => row.stage === stage).length})</span>
              </h2>
              <div className="space-y-3">
                {filteredCandidates.filter((row) => row.stage === stage).map((candidate) => (
                  <div className="rounded-lg border border-[#dedbd0] p-3" key={candidate.id}>
                    <div className="font-medium">{candidate.full_name}</div>
                    <div className="mt-1 text-xs text-[#8a8472]">
                      {positions?.find((position) => position.id === candidate.position_id)?.name || hrT("General application")}
                    </div>
                    <div className="mt-2 space-y-1 text-xs text-[#6d6757]">
                      {candidate.phone && <div>{hrT("Phone")}: {candidate.phone}</div>}
                      {candidate.pinfl && <div>PINFL: {candidate.pinfl}</div>}
                      {candidate.interview_at && <div>{hrT("Interview")}: {new Date(candidate.interview_at).toLocaleString()}</div>}
                    </div>
                    <div className="mt-3 flex gap-2">
                      <select className="input min-w-0 flex-1 text-xs" value={candidate.stage} onChange={(event) => void moveCandidate(candidate, event.target.value)}>
                        {STAGES.map((value) => <option key={value} value={value}>{hrT(value)}</option>)}
                      </select>
                      <button type="button" className="btn" onClick={() => openCandidate(candidate)}>{hrT("View / edit")}</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </LoadState>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing === "new" ? hrT("Add candidate") : hrT("Candidate profile")}
        wide
      >
        <form className="space-y-5" onSubmit={saveCandidate}>
          <section>
            <h3 className="mb-3 font-semibold">{hrT("Personal details")}</h3>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <label><span className="label">{hrT("Last name")} *</span><input className="input" required value={form.last_name} onChange={(event) => setForm({ ...form, last_name: event.target.value })} /></label>
              <label><span className="label">{hrT("First name")} *</span><input className="input" required value={form.first_name} onChange={(event) => setForm({ ...form, first_name: event.target.value })} /></label>
              <label><span className="label">{hrT("Middle name")}</span><input className="input" value={form.middle_name} onChange={(event) => setForm({ ...form, middle_name: event.target.value })} /></label>
              <label><span className="label">{hrT("Date of birth")}</span><input className="input" type="date" value={form.date_of_birth} onChange={(event) => setForm({ ...form, date_of_birth: event.target.value })} /></label>
              <label><span className="label">{hrT("Gender")}</span><select className="input" value={form.gender} onChange={(event) => setForm({ ...form, gender: event.target.value })}><option value="">{hrT("Not specified")}</option><option value="male">{hrT("Male")}</option><option value="female">{hrT("Female")}</option><option value="other">{hrT("Other")}</option></select></label>
              <label><span className="label">{hrT("Nationality")}</span><input className="input" value={form.nationality} onChange={(event) => setForm({ ...form, nationality: event.target.value })} /></label>
            </div>
          </section>

          <section>
            <h3 className="mb-3 font-semibold">{hrT("Identity documents")}</h3>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <label><span className="label">PINFL</span><input className="input" inputMode="numeric" pattern="[0-9]{14}" maxLength={14} value={form.pinfl} onChange={(event) => setForm({ ...form, pinfl: event.target.value.replace(/\D/g, "") })} /></label>
              <label><span className="label">{hrT("Passport / ID number")}</span><input className="input" value={form.passport_number} onChange={(event) => setForm({ ...form, passport_number: event.target.value.toUpperCase() })} /></label>
              <label><span className="label">{hrT("Issued by")}</span><input className="input" value={form.passport_issued_by} onChange={(event) => setForm({ ...form, passport_issued_by: event.target.value })} /></label>
              <label><span className="label">{hrT("Issue date")}</span><input className="input" type="date" value={form.passport_issue_date} onChange={(event) => setForm({ ...form, passport_issue_date: event.target.value })} /></label>
              <label><span className="label">{hrT("Expiry date")}</span><input className="input" type="date" value={form.passport_expiry_date} onChange={(event) => setForm({ ...form, passport_expiry_date: event.target.value })} /></label>
            </div>
          </section>

          <section>
            <h3 className="mb-3 font-semibold">{hrT("Contact and address")}</h3>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <label><span className="label">{hrT("Phone")}</span><input className="input" value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} /></label>
              <label><span className="label">{hrT("Email")}</span><input className="input" type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
              <label><span className="label">{hrT("Country")}</span><input className="input" value={form.country} onChange={(event) => setForm({ ...form, country: event.target.value })} /></label>
              <label><span className="label">{hrT("Region / city")}</span><input className="input" value={form.region} onChange={(event) => setForm({ ...form, region: event.target.value })} /></label>
              <label><span className="label">{hrT("District")}</span><input className="input" value={form.district} onChange={(event) => setForm({ ...form, district: event.target.value })} /></label>
              <label><span className="label">{hrT("Address")}</span><input className="input" value={form.address} onChange={(event) => setForm({ ...form, address: event.target.value })} /></label>
            </div>
          </section>

          <section>
            <h3 className="mb-3 font-semibold">{hrT("Application details")}</h3>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <label><span className="label">{hrT("Department")}</span><select className="input" value={form.department_id} onChange={(event) => setForm({ ...form, department_id: event.target.value })}><option value="">{hrT("Not selected")}</option>{departments?.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label>
              <label><span className="label">{hrT("Position")}</span><select className="input" value={form.position_id} onChange={(event) => setForm({ ...form, position_id: event.target.value })}><option value="">{hrT("Position not selected")}</option>{positions?.map((position) => <option key={position.id} value={position.id}>{position.name}</option>)}</select></label>
              <label><span className="label">{hrT("Stage")}</span><select className="input" value={form.stage} onChange={(event) => setForm({ ...form, stage: event.target.value })}>{STAGES.map((stage) => <option key={stage} value={stage}>{hrT(stage)}</option>)}</select></label>
              <label><span className="label">{hrT("Application date")}</span><input className="input" type="date" value={form.applied_on} onChange={(event) => setForm({ ...form, applied_on: event.target.value })} /></label>
              <label><span className="label">{hrT("Interview date and time")}</span><input className="input" type="datetime-local" value={form.interview_at} onChange={(event) => setForm({ ...form, interview_at: event.target.value })} /></label>
              <label><span className="label">{hrT("Source")}</span><input className="input" value={form.source} onChange={(event) => setForm({ ...form, source: event.target.value })} /></label>
              <label className="sm:col-span-2 lg:col-span-3"><span className="label">{hrT("Notes")}</span><textarea className="input min-h-24" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></label>
            </div>
          </section>

          {message && <div className="text-sm text-red-700">{message}</div>}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn" onClick={() => setEditing(null)}>{hrT("Cancel")}</button>
            <button className="btn btn-primary" disabled={isSaving}>{isSaving ? `${hrT("Saving")}…` : hrT("Save candidate")}</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
