import os
import re
from collections import Counter
from copy import deepcopy

import numpy as np

from api.utils.file_utils import get_project_base_directory
from .recognizer import Recognizer


class LayoutRecognizer(Recognizer):
    def __init__(self, domain):
        self.layout_labels = [
             "_background_",
             "Text",
             "Title",
             "Figure",
             "Figure caption",
             "Table",
             "Table caption",
             "Header",
             "Footer",
             "Reference",
             "Equation",
        ]
        super().__init__(self.layout_labels, domain,
                         os.path.join(get_project_base_directory(), "rag/res/deepdoc/"))

    def __call__(self, image_list, ocr_res, scale_factor=3, thr=0.7, batch_size=16):
        def __is_garbage(b):
            patt = [r"^•+$", r"(版权归©|免责条款|地址[:：])", r"\.{3,}", "^[0-9]{1,2} / ?[0-9]{1,2}$",
                    r"^[0-9]{1,2} of [0-9]{1,2}$", "^http://[^ ]{12,}",
                    "(资料|数据)来源[:：]", "[0-9a-z._-]+@[a-z0-9-]+\\.[a-z]{2,3}",
                    "\\(cid *: *[0-9]+ *\\)"
                    ]
            return any([re.search(p, b["text"]) for p in patt])

        layouts = super().__call__(image_list, thr, batch_size)
        # save_results(image_list, layouts, self.layout_labels, output_dir='output/', threshold=0.7)
        assert len(image_list) == len(ocr_res)
        # Tag layout type
        boxes = []
        assert len(image_list) == len(layouts)
        garbages = {}
        page_layout = []
        for pn, lts in enumerate(layouts):
            bxs = ocr_res[pn]
            lts = [{"type": b["type"],
                    "score": float(b["score"]),
                    "x0": b["bbox"][0] / scale_factor, "x1": b["bbox"][2] / scale_factor,
                    "top": b["bbox"][1] / scale_factor, "bottom": b["bbox"][-1] / scale_factor,
                    "page_number": pn,
                    } for b in lts]
            lts = self.sort_Y_firstly(lts, np.mean([l["bottom"]-l["top"] for l in lts]) / 2)
            lts = self.layouts_cleanup(bxs, lts)
            page_layout.append(lts)

            # Tag layout type, layouts are ready
            def findLayout(ty):
                nonlocal bxs, lts, self
                lts_ = [lt for lt in lts if lt["type"] == ty]
                i = 0
                while i < len(bxs):
                    if bxs[i].get("layout_type"):
                        i += 1
                        continue
                    if __is_garbage(bxs[i]):
                        bxs.pop(i)
                        continue

                    ii = self.find_overlapped_with_threashold(bxs[i], lts_,
                                                                thr=0.4)
                    if ii is None:  # belong to nothing
                        bxs[i]["layout_type"] = ""
                        i += 1
                        continue
                    lts_[ii]["visited"] = True
                    if lts_[ii]["type"] in ["footer", "header", "reference"]:
                        if lts_[ii]["type"] not in garbages:
                            garbages[lts_[ii]["type"]] = []
                        garbages[lts_[ii]["type"]].append(bxs[i]["text"])
                        bxs.pop(i)
                        continue

                    bxs[i]["layoutno"] = f"{ty}-{ii}"
                    bxs[i]["layout_type"] = lts_[ii]["type"]
                    i += 1

            for lt in ["footer", "header", "reference", "figure caption",
                       "table caption", "title", "text", "table", "figure", "equation"]:
                findLayout(lt)

            # add box to figure layouts which has not text box
            for i, lt in enumerate(
                    [lt for lt in lts if lt["type"] == "figure"]):
                if lt.get("visited"):
                    continue
                lt = deepcopy(lt)
                del lt["type"]
                lt["text"] = ""
                lt["layout_type"] = "figure"
                lt["layoutno"] = f"figure-{i}"
                bxs.append(lt)

            boxes.extend(bxs)

        ocr_res = boxes

        garbag_set = set()
        for k in garbages.keys():
            garbages[k] = Counter(garbages[k])
            for g, c in garbages[k].items():
                if c > 1:
                    garbag_set.add(g)

        ocr_res = [b for b in ocr_res if b["text"].strip() not in garbag_set]
        return ocr_res, page_layout
