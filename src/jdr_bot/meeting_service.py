"""Meeting use cases. Discord and SQL stay behind the injected ports."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jdr_bot.domain import (
    ChannelFacts,
    JobRecord,
    JobRewrite,
    JobState,
    MeetingError,
    MeetingList,
    MeetingRecord,
    MeetingState,
    MeetingWrite,
    NewJob,
    NewMeeting,
    active_offsets,
    as_utc,
    parse_title,
    plan_meeting,
    require_distinct_channels,
    require_text_channel,
    require_voice_channel,
    rewrite_jobs,
)
from jdr_bot.policy import LIST_LIMIT
from jdr_bot.ports import (
    ChannelDirectory,
    ChannelDirectoryError,
    Clock,
    MeetingConflict,
    MeetingNotEditable,
    MeetingNotFound,
    MeetingStore,
    ReminderInProgress,
)

_SAVE_CONFLICT = "The meeting could not be saved because it conflicts with an existing reminder."
_IN_PROGRESS = "A reminder is currently being delivered; try again shortly."


class MeetingService:
    """Create, view, update, and cancel guild meetings."""

    def __init__(
        self,
        store: MeetingStore,
        channels: ChannelDirectory,
        clock: Clock,
        *,
        list_limit: int = LIST_LIMIT,
    ) -> None:
        self._store = store
        self._channels = channels
        self._clock = clock
        self._list_limit = list_limit

    async def create(
        self,
        *,
        guild_id: int,
        organizer_id: int,
        title: str,
        start_text: str,
        timezone_name: str,
        text_channel_id: int,
        voice_channel_id: int,
        offsets_text: str,
    ) -> MeetingRecord:
        if guild_id <= 0 or organizer_id <= 0:
            raise MeetingError("The meeting could not be saved.")
        planned = plan_meeting(
            now=self._clock.now(),
            title=title,
            start_text=start_text,
            timezone_name=timezone_name,
            offsets_text=offsets_text,
        )
        text_channel = await self._text_channel(guild_id, text_channel_id)
        voice_channel = await self._voice_channel(guild_id, voice_channel_id)
        require_distinct_channels(text_channel.channel_id, voice_channel.channel_id)
        created_at = as_utc(self._clock.now())
        draft = NewMeeting(
            guild_id=guild_id,
            title=planned.title,
            text_channel_id=text_channel.channel_id,
            voice_channel_id=voice_channel.channel_id,
            starts_at=planned.starts_at,
            timezone_name=planned.timezone_name,
            organizer_id=organizer_id,
            created_at=created_at,
        )
        jobs = tuple(
            NewJob(offset_minutes=item.offset_minutes, due_at=item.due_at)
            for item in planned.reminders
        )
        try:
            return await self._store.insert_meeting(draft, jobs)
        except MeetingConflict:
            raise MeetingError(_SAVE_CONFLICT) from None

    async def view(self, *, guild_id: int, meeting_id: int) -> MeetingRecord:
        if meeting_id <= 0:
            raise MeetingError("Meeting not found.")
        meeting = await self._store.get_meeting(guild_id, meeting_id)
        if meeting is None:
            raise MeetingError("Meeting not found.")
        return meeting

    async def list_scheduled(self, *, guild_id: int) -> MeetingList:
        rows = await self._store.list_meetings(
            guild_id, MeetingState.SCHEDULED, self._list_limit + 1
        )
        truncated = len(rows) > self._list_limit
        return MeetingList(meetings=tuple(rows[: self._list_limit]), truncated=truncated)

    async def update(
        self,
        *,
        guild_id: int,
        meeting_id: int,
        title: str | None = None,
        start_text: str | None = None,
        timezone_name: str | None = None,
        offsets_text: str | None = None,
        text_channel_id: int | None = None,
        voice_channel_id: int | None = None,
    ) -> MeetingRecord:
        current = await self._require_scheduled(guild_id, meeting_id)
        schedule_changed = (
            start_text is not None or timezone_name is not None or offsets_text is not None
        )
        if timezone_name is not None and start_text is None:
            raise MeetingError("Provide the start time when changing the time zone.")
        if (
            title is None
            and not schedule_changed
            and text_channel_id is None
            and voice_channel_id is None
        ):
            raise MeetingError("Provide at least one field to change.")

        new_title = current.title if title is None else parse_title(title)
        new_text_id = current.text_channel_id
        new_voice_id = current.voice_channel_id
        if text_channel_id is not None:
            new_text_id = (await self._text_channel(guild_id, text_channel_id)).channel_id
        if voice_channel_id is not None:
            new_voice_id = (await self._voice_channel(guild_id, voice_channel_id)).channel_id
        require_distinct_channels(new_text_id, new_voice_id)

        starts_at = current.starts_at
        zone = current.timezone_name
        replace_jobs = False
        rewrite = JobRewrite(cancel_ids=(), new_jobs=())
        if schedule_changed:
            if any(job.state is JobState.CLAIMED for job in current.jobs):
                raise MeetingError(_IN_PROGRESS)
            zone = current.timezone_name if timezone_name is None else timezone_name
            planned = plan_meeting(
                now=self._clock.now(),
                title=new_title,
                start_text=start_text if start_text is not None else _local_start_text(current),
                timezone_name=zone,
                offsets_text=offsets_text
                if offsets_text is not None
                else _offsets_text(current.jobs),
            )
            new_title = planned.title
            starts_at = planned.starts_at
            zone = planned.timezone_name
            rewrite = rewrite_jobs(current.jobs, planned.reminders)
            replace_jobs = True

        write = MeetingWrite(
            title=new_title,
            text_channel_id=new_text_id,
            voice_channel_id=new_voice_id,
            starts_at=starts_at,
            timezone_name=zone,
            updated_at=as_utc(self._clock.now()),
            replace_jobs=replace_jobs,
            rewrite=rewrite,
        )
        return await self._write(guild_id, meeting_id, write)

    async def cancel(self, *, guild_id: int, meeting_id: int) -> MeetingRecord:
        if meeting_id <= 0:
            raise MeetingError("Meeting not found.")
        current = await self._store.get_meeting(guild_id, meeting_id)
        if current is None:
            raise MeetingError("Meeting not found.")
        if current.state is not MeetingState.SCHEDULED:
            raise MeetingError("Meeting is already cancelled.")
        if any(job.state is JobState.CLAIMED for job in current.jobs):
            raise MeetingError(_IN_PROGRESS)
        try:
            return await self._store.cancel_meeting(guild_id, meeting_id, as_utc(self._clock.now()))
        except MeetingNotFound:
            raise MeetingError("Meeting not found.") from None
        except MeetingNotEditable:
            raise MeetingError("Meeting is already cancelled.") from None
        except ReminderInProgress:
            raise MeetingError(_IN_PROGRESS) from None

    async def _require_scheduled(self, guild_id: int, meeting_id: int) -> MeetingRecord:
        if meeting_id <= 0:
            raise MeetingError("Meeting not found.")
        meeting = await self._store.get_meeting(guild_id, meeting_id)
        if meeting is None:
            raise MeetingError("Meeting not found.")
        if meeting.state is not MeetingState.SCHEDULED:
            raise MeetingError("Cancelled meetings cannot be changed.")
        return meeting

    async def _write(self, guild_id: int, meeting_id: int, write: MeetingWrite) -> MeetingRecord:
        try:
            return await self._store.update_meeting(guild_id, meeting_id, write)
        except MeetingNotFound:
            raise MeetingError("Meeting not found.") from None
        except MeetingNotEditable:
            raise MeetingError("Cancelled meetings cannot be changed.") from None
        except ReminderInProgress:
            raise MeetingError(_IN_PROGRESS) from None
        except MeetingConflict:
            raise MeetingError(_SAVE_CONFLICT) from None

    async def _text_channel(self, guild_id: int, channel_id: int) -> ChannelFacts:
        return require_text_channel(await self._facts(guild_id, channel_id), guild_id)

    async def _voice_channel(self, guild_id: int, channel_id: int) -> ChannelFacts:
        return require_voice_channel(await self._facts(guild_id, channel_id), guild_id)

    async def _facts(self, guild_id: int, channel_id: int) -> ChannelFacts | None:
        try:
            return await self._channels.describe_channel(guild_id, channel_id)
        except ChannelDirectoryError as error:
            # Provider errors can include request URLs. Do not chain them.
            if error.category == "channel_forbidden":
                raise MeetingError("The bot cannot view that channel.") from None
            raise MeetingError("Could not verify the channel. Try again shortly.") from None


def _local_start_text(meeting: MeetingRecord) -> str:
    try:
        zone = ZoneInfo(meeting.timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise MeetingError("Use an IANA time zone such as America/Los_Angeles.") from None
    return meeting.starts_at.astimezone(zone).strftime("%Y-%m-%d %H:%M")


def _offsets_text(jobs: tuple[JobRecord, ...]) -> str:
    offsets = active_offsets(jobs)
    if not offsets:
        raise MeetingError(
            "Provide reminder offsets as comma-separated minutes, for example 1440,60,15."
        )
    return ",".join(str(offset) for offset in offsets)
