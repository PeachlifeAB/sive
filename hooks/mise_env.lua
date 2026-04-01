-- sive mise env hook
-- Fast path: calls 'sive _mise-env' which reads encrypted per-tag snapshots only.
-- No live Bitwarden calls on the shell hook path.
--
local cmd  = require("cmd")
local json = require("json")
local TAG_PATTERN = "^[a-zA-Z_][a-zA-Z0-9_%-]*$"

local HOME = os.getenv("HOME")
if not HOME then
    error("sive: $HOME is not set — cannot locate snapshot directory")
end
local STATE_DIR = HOME .. "/.local/state/sive"

local function project_file_path()
    return (os.getenv("PWD") or ".") .. "/.sive"
end

local function snapshot_path(vault_name, tag)
    return STATE_DIR .. "/" .. vault_name .. "." .. tag .. ".env.enc"
end

function PLUGIN:MiseEnv(ctx)
    local env = {}
    local tags = ctx.options.tags or {}
    if type(tags) == "string" then
        tags = {tags}
    end
    local valid_tags = {}
    for _, tag in ipairs(tags) do
        if not tag:match(TAG_PATTERN) then
            io.stderr:write("sive: invalid tag name, skipping: " .. tostring(tag) .. "\n")
        else
            table.insert(valid_tags, tag)
        end
    end

    local vault_name = "personal"
    local watch_files = {
        project_file_path(),
    }
    for _, tag in ipairs(valid_tags) do
        table.insert(watch_files, snapshot_path(vault_name, tag))
    end
    if #valid_tags == 0 then
        table.insert(watch_files, snapshot_path(vault_name, "global"))
    end

    local command = "sive _mise-env"
    for _, tag in ipairs(valid_tags) do
        command = command .. " --tag " .. tag
    end

    local ok, out = pcall(cmd.exec, command)
    if not ok or type(out) ~= "string" then
        io.stderr:write("sive: failed to exec _mise-env\n")
    else
        local parse_ok, decoded = pcall(json.decode, out)
        if parse_ok and type(decoded) == "table" then
            for k, v in pairs(decoded) do
                table.insert(env, { key = k, value = tostring(v) })
            end
        else
            io.stderr:write("sive: failed to parse JSON from _mise-env output\n")
        end
    end

    return {
        cacheable   = false,
        env         = env,
        watch_files = watch_files,
    }
end
