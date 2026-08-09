local R = require "rsmm"
R.health.checkpoint("per_mod:Curse_Stack_Shard_Questt")

R.on("ready", function()
    local ok = R.item.register({
        id = "Curse_Stack_Shard_Quest",
        base = "Curse_Stack_Shard_Quest",
        name = "Devil's Pocket",
        description = "20% of collected dream fragments are absorbed by Devil's Pocket until it is full (400 required). Once full, increase crit chance by 50%",
        icon = "Objects\\Icon_Devil_Pocket_Full.png",
        rarity = "Cursed",
    })
    if ok then
        R.log("DevilsPocket: registered Devils_Pocket")
    else
        R.log("DevilsPocket: item reg rejected")
    end
end)
