local R = require("rsmm")
if not R.nameplate or not R.nameplate.update_host_crowns then
    R.log("[host-crown] This test requires the native nameplate SDK.")
    return
end
local previous
R.schedule.every_main(0.5, function()
    local result = R.nameplate.update_host_crowns()
    local found, visible, hosts = 0, 0, 0
    for _, player in ipairs(result.players) do
        if player.status == "found" then found = found + 1 end
        if player.visible then visible = visible + 1 end
        if player.is_host then hosts = hosts + 1 end
    end
    local summary = string.format(
        "status=%s session=%s candidates=%d found=%d hosts=%d visible=%d reason=%s",
        result.status, tostring(result.session_state), #result.players,
        found, hosts, visible, result.reason or "-"
    )
    if summary ~= previous then
        R.log("[host-crown] " .. summary)
        previous = summary
    end
end)
