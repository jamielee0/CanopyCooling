URBAN TREE COOLING — REVIEW PACKET
Jamie Lee  ·  6 August 2026


WHERE THINGS STAND

I finished every feasibility check that comes before the real analysis, and they
told me to stop. Two separate gates failed:

  - The demand-by-dryness interaction cannot be identified from these
    observations. The low-demand/dry box holds 0.553 pass-equivalents and my
    frozen rule needs at least 10.

  - Time of day, my backup question, comes out at 0.110 power when I need 0.80,
    because the late-afternoon flag is 99.4% predictable from the solar geometry
    I have to control for.

I have not opened any ECOSTRESS temperature data, I have not picked the held-out
city, and the 2026 season is still sealed. So there is no cooling estimate in
this packet. That is the result, not an omission.


READING ORDER

  01_START_HERE_Two_Page_Summary.docx
        Two pages. What changed from v1 to v2, what I ran, what came back.
        If you only read one thing, read this.

  02_Full_Progress_Report.docx
        The long version, about 4,700 words, with the evidence tables and the
        figures embedded. Version 2.0 — it supersedes the copy I sent earlier
        that said geometry was only 710 of 911 done.

  03_Key_figures/
        The demand-by-water grid you asked for in your review, rebuilt on the
        five-city sample, plus a check that the empty corner is not an artefact
        of my 30-day window. The README in that folder explains both.
        Important: the shading in these is SAMPLE SIZE, not cooling.


THE EVIDENCE BEHIND EACH CLAIM

  04_Step1_conditions/       F1.1–F1.4, T1.1–T1.2, the M1.1 memo, and the six
                             QA checks. This is the weather feasibility screen.

  05_Step2_pass_census/      F2.1–F2.5, T2.1–T2.3, the six Step-2 checks, the
                             feasibility memo, and the gate record. This is
                             where the 219 usable passes and the 0.553 come from.

  06_Step3_time_of_day/      F3T.1–F3T.5, T3T.1–T3T.3, the eleven required
                             checks, the M3T.1 memo, and the gate record. This
                             is where the 0.110 power comes from.

  07_Decisions_and_provenance/
                             The append-only decision log (58 decisions, every
                             one timestamped), the frozen requirements, the
                             baseline I preserved before starting v2, the
                             Task-1 gate, and the two stop reports. If you want
                             to check that I set a threshold before I saw the
                             result rather than after, this is the folder.


FOR COMPARISON

  08_v1_for_comparison/      The Phoenix response surface from v1, my Section-14
                             results note, and the log showing all fifteen of
                             your review findings closed on 17 July. v1 has a
                             cooling figure; v2 does not, and the summary
                             explains why.


NOT RESULTS

  09_DEMO_ONLY_synthetic_not_results/
                             All 102 remaining guide deliverables, built with
                             made-up data so I could test the code and the file
                             formats. Every figure in it is watermarked. None of
                             the numbers in it mean anything about real trees.
                             I included it only so you can see the intended
                             workflow end to end.


MANIFEST_sha256.txt          SHA-256 of every file in this packet.


WHAT I NEED FROM YOU

The computation is finished, so the next step is a decision rather than more
processing. As I see it there are three real options:

  1. Write up the sampling and identifiability finding as the contribution.
     No new data needed.
  2. Redesign around an endpoint that is not tangled up with solar geometry,
     or find an observation source other than clear-sky ECOSTRESS.
  3. Open the temperature data for a strictly descriptive look, recorded in
     advance as descriptive only. This would permanently end the "method frozen
     before results" claim, including for the held-out city.

I did not want to pick between these on my own, and I did not want to lower my
own thresholds after seeing the result.
