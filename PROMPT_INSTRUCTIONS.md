# Prompt Engineering

Describe the job in natural language — the skill's trigger description is broad, so any prompt that mentions a meeting recording and what you want from it will activate it. Claude then reads `SKILL.md`, runs the preflight, and drives `scripts/run.py` for you.

## Minimal prompt (Claude infers defaults and tells you what it assumed):

> Process this meeting recording: ~/Videos/sprint-grooming-2026-06-10.mp4

## Better prompt 

Fills in the context object, so the summary structure, task extraction, and artifacts match what you actually want:

> Process ~/Videos/sprint-grooming-2026-06-10.mp4. It's a backlog grooming session with
> Alice Ng, Bob Li, and me. Output in English, audience is the team. I want the
> transcript, summary, tasks, and the email — skip slides and the PDF report.

That maps directly onto the pipeline flags: meeting type → `--meeting-type grooming`, the names → `--participants`, the artifact list → `--artifacts transcript 
  summary tasks email`, language → `--output-language en`.

A few phrasings that also trigger it, per the skill description — useful when you don't want to think about parameters:

- "What did we decide in this recording? <path>"
- "Extract the action items from yesterday's standup: <path>"
- "Write up the minutes for this call: <path>"

## Two practical tips:

- **Say who was there if you know**. The participant list lets the speaker-ID stage reconcile voiceprints against expected attendees instead of guessing —
  first-time speakers get registered under real names rather than "Unknown".
- **Mention how many speakers if it's known** ("4 people on the call") — it becomes `--num-speakers 4` and improves diarization.

If a speaker lands in the identification gray zone, Claude will come back mid-run and ask "is this Alice?" rather than guessing — that's the designed behavior, not an error. And if you ever want to force the skill explicitly, `/video-meeting <your request>` works too.

## Examples

### BGT Pactual meeting

> Process ~/Documents/MeetingsProcessing/meetings/BGT\ Pactual/BGT\ Pactual\ -\ First\ RPF\ Session\ -2026-06-10.mp4. It's a first meeting with BGT Pactual with
> Sofia Nightingale, Felipe Leitao, and me. We were 3 people on the call. 
> 
> Output in Portuguese, audience is the myself.
> 
> I want the full transcript, summary, action items and tasks, and a PDF report — skip email and slides.
> 
> Meeting context:
> 
> We discussed the investment strategy and how they would manage my wealth and investments. They presented different investor profiles and explained their investment approach.
> 
> The discussion focused on two main phases:
>
> 1. Accumulation Phase (first 5 years)
>   - No withdrawals from the portfolio. 
>   - Periodic additional contributions. 
>   - Portfolio construction aligned with my risk profile. 
>   - Asset allocation and expected returns. 
>   - Onshore and offshore investment structures. 
>   - Currency diversification and exposure to USD-denominated assets. 
> 2. Retirement Phase (after year 5)
>   - Objective of retiring and living from portfolio income and dividends.
>   - Expected withdrawal strategy.
>   - Portfolio adjustments required to generate recurring income while preserving capital.
>
>We also discussed additional services they could provide, including:
>
> - Flat Management Fee
> - Lombard loans and other credit facilities using investments as collateral.
> - Onshore and offshore wealth structures.
> - International diversification.
> - Banking and wealth management services.
> - Estate and succession planning considerations.
> - Tax and operational aspects of maintaining investments in Brazil and abroad.
>
> Please identify:
>
> - Investor profiles and their investment strategies
> - Key recommendations made by Sofia and Felipe.
> - Proposed asset allocation and investor profile.
> - Advantages and disadvantages of the proposed strategy.
> - Open questions and items requiring follow-up.
> - Any assumptions that should be validated before implementation. 