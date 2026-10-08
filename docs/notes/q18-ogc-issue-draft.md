<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Draft: comment on OGC SensorThings issue #174

**Status: POSTED 2026-10-07** as
<https://github.com/opengeospatial/sensorthings/issues/174#issuecomment-6050541663>
on issue #174 ("Data Quality model extension"), **not** as a new issue.

The posted text differs from the draft below in two ways, both decided at send time:

1. **A section was added on the `Datastream` approach**, because re-reading the thread
   before sending showed the draft ignored its most recent and still-unanswered
   proposal. @uloup argued on 2025-08-24 for *mapping instead of extending* — quality
   flags as `Observation`s in a sibling `Datastream`, sharing `phenomenonTime` — and
   nobody answered in the fourteen months since. We have unusually direct evidence,
   because we already use parallel datastreams for raw versus calibrated, and the
   99.8% false-alarm rate from `_peers` comparing `280` against `0.280` is exactly the
   failure a flags-as-datastream mapping would inherit. Posting a comment that talked
   past the live question would have been the "repeats rather than adds" failure the
   checklist below was written to prevent.
2. **The project is not linked**, reversing the draft's recommendation below. The
   reason is circumstance, not reconsideration: the repository is private, so a link
   would have been a 404 in a standards thread, which costs more credibility than the
   link would buy. The offer to share the model and to test a proposal against a
   working endpoint carries the same weight and costs nothing. Revisit when the
   repository is public.

The threshold-versioning paragraph also gained a direct question back to the thread —
under the `Datastream` mapping, a mid-season retune forces a choice between forking a
datastream per retune or mutating the procedure and losing the ability to explain an
old flag. That is the one thing we could not answer for ourselves, so it is worth
asking the people who have thought about it longer.

Everything below is the draft as it stood before sending, kept because the reasoning
about what *not* to send is the part worth keeping.

## What changed from the first draft, and why

The first draft asked "was removing `resultQuality` from 2.0 intentional?" and argued
for restoring it. **Both were wrong**, and a search of the repository before posting
is what caught it:

- **#174** was opened by **hylkevds** — the 2.0 editor — in January 2024, labelled
  `sensing v2.0` / `data model`. Its opening line: *"Since no one really knows what
  to do with the resultQuality DQ_Element property on Observation, we need something
  better. Some proposals are currently being worked on."* The removal is deliberate
  and the replacement is in progress.
- **#68** (2019, open) documents exactly why `DQ_Element` was unusable: it is
  ambiguous between ISO 19115 and 19157, and `DQ_Result` has no category type for
  validation levels.
- 16 comments on #174 carry a worked design — `QualityMetric`, `QualityAnnotation`,
  `QualitySetup`, `HistoricalQualityAnnotation` — from the EU CitiObs project and
  from UFZ's `saqc` anomaly-detection work.

So asking them to restore `DQ_Element` would have been asking for the thing they
already decided was broken, in a thread that had already said so. The useful
contribution is the opposite direction: **#174 has four questions still open, and we
have an implementation that had to answer all four.** That is what the comment below
supplies.

Last activity on #174 was 2025-08-25; the 2.0 draft was submitted 2025-11-26 without
a quality model.

---

## The comment

I have been building an open data and device contract for small farms — soil
moisture, irrigation, livestock water — and the sensing side publishes through a
SensorThings-compatible endpoint. Quality was the hardest part of our data model to
get right, and in working through it we ended up answering several of the questions
still open in this thread. Offering what we found, in case the evidence is useful.

Caveat up front: this is an implementation with tests, not a deployment with a field
season behind it. Treat it as a worked example rather than as operational experience.

**On cardinality — 0..1 or 0..\* annotations per Observation.** We think there is a
third option that dissolves the question. We first tried one annotation per check,
and it loses information: when a flatline check and a range check both fire on the
same reading, something has to choose which annotation is "the" current one, and the
other check's finding silently disappears. That is a quiet failure of exactly the
kind quality flags exist to prevent — we have a test that demonstrates it rather than
asserting it.

What we settled on is **one annotation per assessment run, carrying a set of flags**.
A run is "the suite of checks that looked at this reading, under this configuration";
its flags are the union of everything that fired. So an Observation has several
annotations over time (re-assessments, corrections, human review) but exactly one
*current* one, and multiple simultaneous findings live inside it rather than
competing with each other. Cardinality stays 0..\* over history and effectively 1 for
"what does this reading mean right now", without needing `HistoricalQualityAnnotation`
to make that distinction.

**On "compound data types are harder for the client".** That was our experience too,
and we handled it by carrying both: the flag set, plus a single derived summary value
(`good` / `questionable` / `bad`). A client that does not care about detail reads one
scalar; a client that does reads the set. The important part is that the summary is
*derived from* the flags by one published function, so two implementations cannot
disagree about what a given set of flags means. If a standard specifies the mapping,
the simple client gets portability for free.

**On history and on how many requests a change takes.** Rather than a separate
`Historical*` entity, we put a `supersedes` pointer on the annotation itself: a new
annotation names the one it replaces, and the live one is whichever nothing
supersedes. In practice this answers the POST/PATCH question raised above — a
re-assessment is one POST, the Observation is never touched, and the superseded
annotation stays readable forever. We found resolving "live" by set difference also
handles chains for free.

**On storing the parameters a measure was configured with.** Strongly agree this is
needed. We made thresholds versioned records and have each annotation name the
version it used. The payoff is specific: when a farmer retunes a threshold, the old
annotations keep the old version, so a false alarm stays traceable to the threshold
that caused it and a retune cannot silently re-flag history. Without the version
reference you can tell *that* something was flagged but not *under what rule*, and
for us that distinction is what certification auditors actually ask about.

**One thing I have not seen raised here: human override.** Every QA/QC workflow we
looked at has a step where a person disagrees with the automated verdict — the probe
was out of the ground, the sample was mislabelled. We model that as an annotation
with `assertor: person`, outranking machine annotations by precedence, with the
machine's original left intact and visible. The requirement it creates for a standard
is small but real: whatever carries the annotation needs somewhere to say *who or
what asserted this*, or an automated re-run will quietly overwrite a human judgement.

Happy to share the model in detail, or to implement a proposal from this thread
against a working endpoint and report what breaks — that seemed to be what was wanted
when compound types came up as "requiring some real-world testing".

---

## Before sending

- [x] Searched for existing issues — found #174, #68, #155. **Do not open a new
      issue.**
- [x] Read all 16 comments on #174 so the comment adds rather than repeats.
- [x] Re-confirmed the draft: re-fetched 23-019, still stamped v0.1 / 2025-11-26,
      zero occurrences of `resultQuality` or `DQ_Element`, Table 17 has six
      attributes.
- [ ] **Decide whether to name the project.** The comment currently does not link it.
      Linking makes the claims checkable and the offer at the end credible; not
      linking keeps it about the standard. Given the final paragraph offers to test
      a proposal, a link probably helps.
- [ ] Decide whether to also leave a short note on **#68**, which is the narrower
      `DQ_Element` issue, pointing at #174 — or leave it alone, since #174
      supersedes it.
- [ ] Consider trimming. The cardinality and the parameter-provenance paragraphs
      are the load-bearing ones; the summary-value and human-override paragraphs are
      the most novel. The history paragraph could go if length is a problem.
- [ ] Tone check: this is a thread of people who have thought about it longer than
      we have. The caveat in the second paragraph should stay.

## Supporting material, if asked

- Our quality model: [spec/v0.1.md](../spec/v0.1.md) §3.3, and the amendment in §17
  recording why one-annotation-per-run replaced one-per-check.
- The test that demonstrates the loss: `sdk/test_checks.py`,
  `test_separate_assertions_per_check_would_lose_a_flag`.
- Threshold versioning and retuning without rewriting history:
  `sdk/test_checks.py::TestReassessment`.
- FROST-Server round-trips a structured quality array unchanged, including nested
  content — [frost-validation.md](frost-validation.md).
