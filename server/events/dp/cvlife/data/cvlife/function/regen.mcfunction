# Player healing (naturalRegeneration is off). Every second a player with 9+ drumsticks and missing health counts
# up, twice as fast with a full bar; at 10 they heal 2 hearts. With hunger off (Saturation in cvlife:loop) the bar
# stays full, so that is 2 hearts every 5 s.
scoreboard players add @a[scores={cv_food=18..,cv_hp=..19}] cv_regen 1
scoreboard players add @a[scores={cv_food=20,cv_hp=..19}] cv_regen 1
scoreboard players set @a[scores={cv_food=..17}] cv_regen 0
execute as @a[scores={cv_regen=10..}] run effect give @s instant_health 1 0 true
scoreboard players set @a[scores={cv_regen=10..}] cv_regen 0
