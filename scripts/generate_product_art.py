from pathlib import Path

ITEMS = [
    ("blouse", "浅云纯棉衬衫", "女装", "#d8e8ed", "shirt"),
    ("skirt", "柔雾针织半身裙", "女装", "#e8dce9", "skirt"),
    ("hoodie", "轻暖休闲卫衣", "女装", "#f3ddc8", "hoodie"),
    ("jacket", "城市休闲夹克", "男装户外", "#d6e0dc", "jacket"),
    ("activewear", "轻跑运动上衣", "运动户外", "#dce9f2", "shirt"),
    ("charger", "USB-C 桌面充电器", "数码配件", "#e0e1ed", "charger"),
    ("earbuds", "蓝牙无线耳机", "数码配件", "#efe1d3", "earbuds"),
    ("lamp", "暖光陶瓷台灯", "家居生活", "#f1e2c8", "lamp"),
    ("shelf", "木纹收纳置物架", "家居生活", "#e8d6bc", "shelf"),
    ("cleanser", "清润洁面乳", "美妆个护", "#dcece5", "bottle"),
    ("wipes", "棉柔巾家庭装", "美妆个护", "#eee3da", "wipes"),
    ("plush", "软萌安抚玩偶", "母婴玩具", "#f2dddd", "plush"),
    ("nuts", "轻烘焙坚果分享装", "食品分享", "#efdfc5", "nuts"),
    ("tote", "帆布日常托特包", "鞋包配饰", "#e5d9c4", "tote"),
    ("pet-bed", "软绒宠物休息垫", "宠物生活", "#e1e7d8", "bed"),
    ("organizer", "车载折叠收纳箱", "汽车用品", "#dfe3e5", "box"),
    ("journal", "生活灵感手账本", "文娱文具", "#efe0cb", "book"),
    ("pillbox", "便携分格收纳盒", "日常收纳", "#dce8e3", "box"),
    ("pen-holder", "桌面笔筒收纳架", "办公文具", "#e0e5e9", "holder"),
    ("tool-bag", "手动工具收纳包", "工业用品", "#dedbd2", "toolbag"),
    ("mug", "简约陶瓷马克杯", "生活好物", "#ece0d4", "mug"),
    ("hat", "春日轻盈渔夫帽", "帽子配饰", "#e8dfd3", "hat"),
]

INK = "#796c60"


def artwork(kind: str) -> str:
    shapes = {
        "shirt": '<path d="m220 165 57-34 43 29 43-29 57 34 52 91-54 31-35-47v151H257V240l-35 47-54-31z"/><path d="m277 131 43 29-27 55-36-42v-26m106-16-43 29 27 55 36-42v-26" fill="#fff"/><path d="M320 160v202m-59-93h43m-43 22h43m74-22h-38m38 22h-38" fill="none" stroke="%s" stroke-width="5"/>' % INK,
        "skirt": '<path d="M267 139q53 24 106 0l15 57 67 150q-135 50-270 0l67-150z"/><path d="M267 198h106m-123 54h140m-165 55h190" fill="none" stroke="%s" stroke-width="6" opacity=".5"/>' % INK,
        "hoodie": '<path d="M258 168q3-65 62-65t62 65l47 24 47 103-56 29-32-52v103H210V272l-32 52-56-29 47-103z"/><path d="M282 137q38 30 76 0m-38 29v72m-44 25v42m88-42v42" fill="none" stroke="%s" stroke-width="7"/>' % INK,
        "jacket": '<path d="m228 155 51-26 41 29 41-29 51 26 51 97-51 29-29-38v135H257V243l-29 38-51-29z"/><path d="M320 158v220m-39-194 39 35 39-35m-99 74h33m54 0h33" fill="none" stroke="%s" stroke-width="7"/>' % INK,
        "charger": '<rect x="207" y="170" width="226" height="190" rx="36"/><rect x="268" y="120" width="25" height="55" rx="8"/><rect x="347" y="120" width="25" height="55" rx="8"/><circle cx="320" cy="265" r="48" fill="#fff"/><path d="M320 230v70m-23-47h46" fill="none" stroke="%s" stroke-width="12"/>' % INK,
        "earbuds": '<path d="M202 258a118 118 0 0 1 236 0v83q0 48-46 48t-46-48v-60q0-42 43-42m-231 19v83q0 48 46 48t46-48v-60q0-42-43-42" fill="none" stroke="%s" stroke-width="24"/><path d="M258 400h124" fill="none" stroke="%s" stroke-width="13"/>' % (INK, INK),
        "lamp": '<path d="M208 222h224l-39-105H247z"/><path d="M320 222v120m-68 40h136l-20-40h-96z"/><path d="M263 160h114" fill="none" stroke="%s" stroke-width="7" opacity=".5"/>' % INK,
        "shelf": '<path d="M214 118v264m212-264v264M202 191h236m-236 91h236m-236 91h236" fill="none" stroke="%s" stroke-width="18"/><rect x="235" y="140" width="48" height="40" rx="8"/><rect x="340" y="232" width="60" height="49" rx="8"/><path d="M230 350h62" stroke="#b48759" stroke-width="14"/>' % INK,
        "bottle": '<rect x="233" y="157" width="174" height="229" rx="49"/><path d="M276 157v-40h88v40m-132 75h176"/><rect x="272" y="254" width="96" height="74" rx="16" fill="#fff"/><path d="M297 286h46" fill="none" stroke="%s" stroke-width="8"/>' % INK,
        "wipes": '<path d="M205 183q115-49 230 0v189q-115 49-230 0z"/><path d="M273 170q47-93 94-2m-83 1q30-53 59-1" fill="none" stroke="%s" stroke-width="13"/><path d="M235 270h170m-170 32h137" fill="none" stroke="%s" stroke-width="6"/>' % (INK, INK),
        "plush": '<circle cx="320" cy="254" r="101"/><circle cx="247" cy="178" r="43"/><circle cx="393" cy="178" r="43"/><circle cx="285" cy="243" r="9" fill="%s"/><circle cx="355" cy="243" r="9" fill="%s"/><ellipse cx="320" cy="281" rx="24" ry="17" fill="%s"/><path d="M305 309q15 19 30 0m-105 68q35-56 90-22 55-34 90 22" fill="none" stroke="%s" stroke-width="13" stroke-linecap="round"/>' % (INK, INK, INK, INK),
        "nuts": '<path d="M189 233q0-37 42-37h178q42 0 42 37v126q0 41-42 41H231q-42 0-42-41z"/><path d="M189 256h262" fill="none" stroke="%s" stroke-width="15"/><g fill="#c48e52" stroke="%s" stroke-width="5"><ellipse cx="260" cy="307" rx="24" ry="14" transform="rotate(-24 260 307)"/><ellipse cx="320" cy="336" rx="24" ry="14" transform="rotate(18 320 336)"/><ellipse cx="379" cy="300" rx="24" ry="14" transform="rotate(-13 379 300)"/></g>' % (INK, INK),
        "tote": '<path d="M218 216h204l23 174H195z"/><path d="M257 220v-47q0-74 63-74t63 74v47" fill="none" stroke="%s" stroke-width="16"/><path d="M240 268h160m-147 81h134" fill="none" stroke="%s" stroke-width="7" opacity=".6"/>' % (INK, INK),
        "bed": '<ellipse cx="320" cy="304" rx="171" ry="96"/><ellipse cx="320" cy="288" rx="126" ry="61" fill="#fff" opacity=".5"/><path d="M230 278q90 62 180 0m-155 51q65 43 130 0" fill="none" stroke="%s" stroke-width="7"/><circle cx="272" cy="278" r="8" fill="%s"/><circle cx="368" cy="278" r="8" fill="%s"/>' % (INK, INK, INK),
        "box": '<path d="M196 214h248v166H196z"/><path d="m196 214 124-71 124 71m-248 0 124 72 124-72M320 286v94" fill="none" stroke="%s" stroke-width="9"/><rect x="285" y="203" width="70" height="24" rx="8" fill="#fff"/>' % INK,
        "book": '<path d="M218 130h205v260H218z"/><path d="M247 130v260m27-190h118m-118 32h118m-118 32h85" fill="none" stroke="%s" stroke-width="8"/><path d="m330 288 15 30 33 5-24 23 6 33-30-16-30 16 6-33-24-23 33-5z" fill="#fff" stroke="%s" stroke-width="5"/>' % (INK, INK),
        "holder": '<path d="M242 190h156l-17 182H259z"/><path d="M268 190q52-54 104 0m-94 55h84m-89 36h94" fill="none" stroke="%s" stroke-width="8"/><path d="M278 189v-47m42 47v-68m42 68v-42" stroke="#bd815b" stroke-width="10" stroke-linecap="round"/>' % INK,
        "toolbag": '<path d="M197 220h246v153H197z"/><path d="M257 220v-42q0-24 25-24h76q25 0 25 24v42m-186 35h246" fill="none" stroke="%s" stroke-width="14"/><path d="m258 293 28-28m-20 48 36-36m43-8 40 40m-29-49 38 38" stroke="#f7f1e7" stroke-width="13" stroke-linecap="round"/>' % INK,
        "mug": '<path d="M215 190h188v166q0 41-43 41h-102q-43 0-43-41z"/><path d="M403 228h38q55 0 55 53t-55 53h-38" fill="none" stroke="%s" stroke-width="20"/><path d="M235 232h148" fill="none" stroke="#fff" stroke-width="13" opacity=".65"/>' % INK,
        "hat": '<path d="M203 273q14-113 117-135 103 22 117 135-117-34-234 0z"/><path d="M163 270q157-61 314 0l-28 49q-129 43-258 0z"/><path d="M251 207q69 27 138 0" fill="none" stroke="#fff" stroke-width="10" opacity=".7"/>',
    }
    return shapes[kind]


def main():
    output = Path(__file__).resolve().parents[1] / "public" / "images"
    for slug, name, category, color, kind in ITEMS:
        art = artwork(kind)
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 560" role="img" aria-labelledby="title desc"><title id="title">{name}</title><desc id="desc">{name}原创商品演示插画</desc><defs><linearGradient id="background" x2="0" y2="1"><stop stop-color="#faf8f3"/><stop offset="1" stop-color="{color}"/></linearGradient><linearGradient id="object" x2="1" y2="1"><stop stop-color="#fff"/><stop offset="1" stop-color="{color}"/></linearGradient><filter id="shadow" x="-.3" y="-.3" width="1.6" height="1.7"><feDropShadow dx="0" dy="12" stdDeviation="12" flood-color="#55473c" flood-opacity=".16"/></filter></defs><rect width="640" height="560" rx="28" fill="url(#background)"/><circle cx="510" cy="105" r="55" fill="#fff" opacity=".48"/><g filter="url(#shadow)" fill="url(#object)" stroke="{INK}" stroke-width="7" stroke-linejoin="round">{art}</g><rect x="32" y="430" width="576" height="96" rx="22" fill="#fff" opacity=".78"/><text x="320" y="472" text-anchor="middle" fill="#51473e" font-family="sans-serif" font-size="27" font-weight="700">{name}</text><text x="320" y="505" text-anchor="middle" fill="#8d7c6b" font-family="sans-serif" font-size="17">{category} · 原创演示插画</text></svg>'''
        (output / f"{slug}.svg").write_text(svg, encoding="utf-8")
    print(f"Generated {len(ITEMS)} product illustrations in {output}")


if __name__ == "__main__":
    main()
