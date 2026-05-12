"""Raw episodes — the inputs to the extraction pipeline.

Each episode has real-looking content (a Zoom transcript fragment, a
Slack thread) plus the entity refs that the extractor would have
produced. The seeder writes both, so the Episode detail page is not
empty on first load. The episode is left at status="pending" so the
user can kick reprocess and watch the real pipeline run against the
same content.
"""

from datetime import UTC, datetime

from seeds.demo.halcyon._types import EpisodeSeed


def _dt(y: int, m: int, d: int, h: int = 12, mn: int = 0) -> datetime:
    return datetime(y, m, d, h, mn, tzinfo=UTC)


_OCT_SYNC_TRANSCRIPT = """\
[Zoom — weekly founders sync, Oct 6 2025, 09:02 PT]

Sarah: OK, let's start with Zephyr. Where are we.

Alex: Bad. Jordan filed a ticket Thursday. The eval runner's scoring is
non-deterministic on their prompts. They re-ran three times, got
different scores. I've seen the notebook. He's right.

Sarah: How did we not catch this?

Alex: We seed the sampler off wall-clock. For our internal runs it
basically looks deterministic because all the prompts are short and the
model temperature is low. Zephyr has these weird borderline numeric
reasoning prompts that trip it.

Sarah: How fast can we fix it.

Alex: Fix is small. A day of work. What's going to take longer is
rebuilding trust with Jordan.

Sarah: I'll call him today. We should also think about how we say this
to the rest of the pilot teams. Is anyone else going to hit it?

Alex: Probably not at the scale Zephyr is. But if we don't tell them
and they find out, that's worse.

Sarah: Agreed. Write it up. I'll talk to Jordan, then we decide.
"""

_NOV_SLACK_EXPORT = """\
[Slack #halcyon-general, Nov 19 2025]

sarah (11:42): Zephyr just countersigned. 1-year, 84K. 🎉
alex (11:42): 🙌
marcus (11:43): hell yes. took us long enough.
elena (11:44): i'll put orbit 1.1 into their tenant tonight. current
staging gets wiped, real run tomorrow.
priya (11:47): pinned in #marketing so we can shape an announcement.
not rushing it — let the re-sign stand on its own for a week or two.
marcus (11:50): jordan asked if he can be a reference. told him yes
pending sarah. @sarah ok?
sarah (11:52): yes, absolutely. Let's get him on the next 2-3 customer
intro calls.
alex (12:02): reminder: we said in the postmortem that every
customer-facing perf claim runs through the repro harness before we put
it in a pitch deck. that still stands.
sarah (12:03): ack. marcus - pull the current deck, anything that says
"4%" or "99%" needs a source.
marcus (12:03): on it. will circulate by friday.
"""

EPISODES: tuple[EpisodeSeed, ...] = (
    EpisodeSeed(
        key="episode.oct_sync_transcript",
        source_kind="meeting_transcript",
        source_ref="zoom/founders-sync/2025-10-06",
        occurred_at=_dt(2025, 10, 6, 16, 2),  # 09:02 PT = 16:02 UTC
        content_text=_OCT_SYNC_TRANSCRIPT,
        extracted_entity_keys=(
            "person.sarah_chen",
            "person.alex_park",
            "person.jordan_reyes",
            "org.zephyr_data",
            "project.orbit",
        ),
    ),
    EpisodeSeed(
        key="episode.nov_slack_celebration",
        source_kind="slack_export",
        source_ref="slack/halcyon-general/2025-11-19",
        occurred_at=_dt(2025, 11, 19, 19, 42),  # 11:42 PT = 19:42 UTC
        content_text=_NOV_SLACK_EXPORT,
        extracted_entity_keys=(
            "person.sarah_chen",
            "person.alex_park",
            "person.marcus_webb",
            "person.elena_kowalczyk",
            "person.priya_raghavan",
            "person.jordan_reyes",
            "org.zephyr_data",
            "project.orbit",
        ),
    ),
)
