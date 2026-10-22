# Nix Hermes + Discord pilot

This is a **standalone, non-destructive cutover candidate**, NOT the existing Nix Compose stack.
It runs Hermes with two persistent profiles (LNX, LNO) and Discord as the human-facing interface.
There are deliberately **no Paperclip, Telegram, PostgreSQL, web dashboard, or public API ports**.
Todoist remains the canonical task board and GitHub remains code/durable knowledge, but their credentials are NOT configured by this pilot.

## 0. Preconditions and rollback boundary

- SSH into the VPS; do not paste secrets into GitHub, Discord, or this repository.
- Check available CPU/RAM, existing Docker containers, host disk, and existing deployment backups.
- The old Compose project is untouched. One migration caveat: this pilot does not implement automatic LNX-to-LNO task handoff; internal Bot Mode rooms require additional, explicit initialization. Until then, humans coordinate through Discord and Todoist. It must **not** be removed until this pilot passes acceptance tests and required state is preserved.
- Each Discord bot needs its **own token**; never reuse the old Telegram token or share a token across profiles.
- Create a private Discord channel such as #nix-agent-test and initially allow only the founder to invoke tools.

## 1. Prepare a versioned image and private data directory

From this directory on the VPS:

~~~bash
cp .env.example .env
docker pull nousresearch/hermes-agent:0.22.3
docker image inspect --format '{{index .RepoDigests 0}}' nousresearch/hermes-agent:0.22.3
~~~

Copy the verified repo@sha256 digest into HERMES_IMAGE in the local .env before production use. If the example tag does not resolve, select an actually published release and verify its digest; do not use a floating latest tag for production.
Do not commit .env. Confirm the digest matches the intended platform and stable release.

~~~bash
sudo install -d -m 0700 -o 10000 -g 10000 /srv/nix-hermes-discord/data
docker compose -f compose.yaml config --quiet
docker compose -f compose.yaml up -d
~~~

No inbound Docker ports are published; Discord uses an outbound connection.

## 2. Register the two Hermes profiles

~~~bash
docker exec nix-hermes-discord hermes profile create lnx --description "Nix CEO and task coordination"
docker exec nix-hermes-discord hermes profile create lno --description "Nix CTO and engineering execution"
docker exec -i --user 10000:10000 nix-hermes-discord sh -c 'cat > /opt/data/profiles/lnx/SOUL.md' < roles/lnx/SOUL.md
docker exec -i --user 10000:10000 nix-hermes-discord sh -c 'cat > /opt/data/profiles/lno/SOUL.md' < roles/lno/SOUL.md
~~~

If profiles already exist from a previous pilot, inspect them before replacing their SOUL files.

## 3. Create two Discord applications

Create **LNX** and **LNO** in https://discord.com/developers/applications.
For each: enable Message Content Intent; use the bot install/invite flow for the private Nix server, without Administrator permission.
Grant only the channel and message permissions needed to operate in #nix-agent-test.
Copy your numeric Discord user ID and the test channel ID using Discord Developer Mode.

Configure a model/provider and a unique Discord bot token for each profile through the interactive Hermes setup:
    
~~~bash
docker exec -it nix-hermes-discord hermes -p lnx setup
docker exec -it nix-hermes-discord hermes -p lno setup
~~~

Verify the PRIVATE files exist at /srv/nix-hermes-discord/data/profiles/lnx/.env and .../lno/.env.
Using a secure local editor on the VPS, ensure each profile .env contains:

~~~dotenv
DISCORD_BOT_TOKEN=<that profile's Discord token>
DISCORD_ALLOWED_USERS=<founder's numeric Discord user ID>
DISCORD_ALLOWED_CHANNELS=<numeric test channel ID>
DISCORD_REQUIRE_MENTION=true
DISCORD_THREAD_REQUIRE_MENTION=true
DISCORD_ALLOW_BOTS=none
API_SERVER_ENABLED=false
~~~

These are illustrative entries, **not** values to paste into Git. Make the files mode 0600,
owned by UID 10000, and do not print their contents to logs or chat.

Start each profile under the image's built-in supervisor:

~~~bash
docker exec nix-hermes-discord hermes -p lnx gateway start
docker exec nix-hermes-discord hermes -p lno gateway start
docker exec nix-hermes-discord hermes -p lnx gateway status
docker exec nix-hermes-discord hermes -p lno gateway status
~~~

## 4. Acceptance tests (performed from Discord)

1. In #nix-agent-test, mention LNX. Confirm only LNX responds, accurately identifies its CEO role, and maintains context across follow-ups.
2. Mention LNO. Confirm only LNO responds, identifies its CTO role, and does not inherit LNX's private session history.
3. Send a normal unmentioned message and a message from another Discord bot. Neither Hermes bot should respond.
4. Try an unauthorized human account. Confirm the request is rejected or ignored.
5. Restart the pilot only: docker restart nix-hermes-discord. Verify both profiles are supervised and both bots reconnect without prompting for credentials.
6. Request a *read-only* task, then inspect errors and logs without copying secrets.
7. Confirm there are no published ingress ports or Docker-socket mounts.

For logs, use:

~~~bash
docker logs --tail 100 nix-hermes-discord
docker exec nix-hermes-discord hermes -p lnx gateway status
docker exec nix-hermes-discord hermes -p lno gateway status
~~~

Do not claim the full business workflow works until Todoist and GitHub are configured and a genuine task-to-PR test passes.

## 5. Agent collaboration and state ownership

**Do not mirror Hermes Bot Mode rooms into Discord.** Discord bot replies are human-triggered;
DISCORD_ALLOW_BOTS=none prevents the unsupported auto-reply topology from creating loops.
Hermes profiles and their Discord sessions work headlessly; the Desktop Bot Mode roster and
canonical internal Bot Chats are a separate capability and do not automatically appear in Discord.
Enabling internal Bot Mode message_agent requires canonical Bot Chat sessions and its UI metadata
marker; test that separately using the official Bot Mode documentation if needed.

Todoist is the authoritative queue for multi-agent work assignments once connected.
Do not use Discord messages or Hermes's optional Kanban as another human task board.
GitHub owns implementation artifacts and durable technical knowledge.

## 6. Rollback and later cutover

To stop only this pilot:

~~~bash
docker compose -f compose.yaml down
~~~

Never use down -v; preserve /srv/nix-hermes-discord/data, which includes secrets, sessions, and memory.
This command does not touch the old Nix Compose project or its volumes.

After the pilot passes, separately plan the final migration: connect least-privilege Todoist/GitHub
credentials, test a task -> PR workflow, back up both stacks, then retire the old
Paperclip/Telegram deployment. Do not delete its containers or volumes in this PR.

Official references:
- https://hermes-agent.nousresearch.com/docs/user-guide/docker
- https://hermes-agent.nousresearch.com/docs/user-guide/profiles
- https://hermes-agent.nousresearch.com/docs/user-guide/messaging/discord
- https://hermes-agent.nousresearch.com/docs/user-guide/bot-mode
