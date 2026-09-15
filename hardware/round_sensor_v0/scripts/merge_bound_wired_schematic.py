"""Preserve reviewed online footprint bindings in the newly wired SCH-A2 pages."""

from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[1] / "easyeda_std"
BOUND = ROOT / "SCH_round_sensor_SCH_A2_bound60_2026-09-15.json"
WIRED = ROOT / "round_sensor_SCH_A2_multi.json"
OUT = ROOT / "round_sensor_SCH_A2_WIRED_multi.json"


def ref_of(lib):
    refs = [part.split("~")[12] for part in lib.split("#@$#") if part.startswith("T~P~")]
    if not refs:
        refs = [part.split("~")[12] for part in lib.split("#@$") if part.startswith("T~P~")]
    assert len(refs) == 1, refs
    return refs[0]


def package_of(head):
    attrs = head.split("~")[3].split("`")
    values = dict(zip(attrs[::2], attrs[1::2]))
    return values.get("package", "")


def bind_header(wired_lib, bound_lib):
    wired_parts = wired_lib.split("#@$")
    bound_head = bound_lib.split("#@$", 1)[0].split("~")
    wired_head = wired_parts[0].split("~")
    assert len(bound_head) >= 16 and bound_head[15], (ref_of(bound_lib), "missing footprint UUID")
    assert package_of("~".join(bound_head)), (ref_of(bound_lib), "empty package")

    # 保留新生成的中文属性与图形位置，仅复制已审查的封装名、符号库 UUID
    # 和封装 UUID，避免旧版英文审查备注覆盖中文版本。
    wired_attrs = wired_head[3].split("`")
    attrs = dict(zip(wired_attrs[::2], wired_attrs[1::2]))
    attrs["package"] = package_of("~".join(bound_head))
    wired_head[3] = "`".join(str(z) for pair in attrs.items() for z in pair) + "`"
    wired_head[7] = bound_head[7]
    wired_head.extend([""] * (16 - len(wired_head)))
    wired_head[15] = bound_head[15]
    wired_parts[0] = "~".join(wired_head)
    return "#@$".join(wired_parts)


def main():
    bound = json.loads(BOUND.read_text())
    wired = json.loads(WIRED.read_text())
    bound_sheets = {sheet["title"]: sheet for sheet in bound["schematics"]}
    assert set(bound_sheets) == {sheet["title"] for sheet in wired["schematics"]}

    packages = {}
    for sheet in wired["schematics"]:
        title = sheet["title"]
        bound_libs = {
            ref_of(shape): shape
            for shape in bound_sheets[title]["dataStr"]["shape"]
            if shape.startswith("LIB~")
        }
        wired_refs = {ref_of(shape) for shape in sheet["dataStr"]["shape"] if shape.startswith("LIB~")}
        assert wired_refs == set(bound_libs), (title, wired_refs ^ set(bound_libs))
        merged = []
        for shape in sheet["dataStr"]["shape"]:
            if shape.startswith("LIB~"):
                ref = ref_of(shape)
                shape = bind_header(shape, bound_libs[ref])
                packages[ref] = package_of(shape.split("#@$", 1)[0])
            merged.append(shape)
        sheet["dataStr"]["shape"] = merged

    assert len(packages) == 60 and all(packages.values()), len(packages)
    wired["title"] = "圆形传感器_SCH_A2_中文最终版"
    wired["description"] = "SCH-A2 中文五页原理图，功能块内采用连续导线，并保留 60 个已审查封装绑定"
    OUT.write_text(json.dumps(wired, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": OUT.name, "sheets": 5, "bound_footprints": len(packages)}))


if __name__ == "__main__":
    main()
