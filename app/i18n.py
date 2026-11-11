TEXT = {
    "zh": {
        "intro": "请上传Telegram里的**原图**（保存图片或复制图片），请勿截图或缩放。  \n关于此验证码：[{site}]({article})",
        "upload": "验证码",
        "hint": "填写题目所给的“共有X个区域”以提高准确率",
        "force": "仍然尝试",
        "reset": "重新上传",
        "recovery": "若验证码不接受此答案，点此查看其他候选",
        "answer_image": "答案",
        "previous": "上一个",
        "next": "下一个候选答案",
        "examples": "示例：绝对绝望样本",
        "answer": "## 答案：{cells}",
        "candidate": "第 {index} / {count} 个候选",
        "added": "新增{cells}",
        "removed": "移除{cells}",
        "change_separator": "，",
        "changes": "与上一个候选相比：{changes}（绿框为新增，红框为移除）",
        "last": "这是最后一个候选。若仍未出现验证码接受的答案，请更换题目。",
        "gates": {
            "empty": "### 这不是验证码图片\n\n图中没有识别到任何手性碳。请上传Telegram中的验证码原图。",
            "not_original": "### 似乎不是原图\n\n这张图可能是截图，或被裁剪、缩放过，结果可能不准确。",
            "unreliable": "### 本题答案不可靠\n\n这张图难以阅读，或该分子没有唯一的正确答案，建议更换题目。",
            "ambiguous": "### 本题答案真随机！\n\n这张图包含每次都不同的随机答案，建议更换题目。",
        },
        "reminders": {
            "not_original": "这张图不是原图，答案可能不准确。",
            "unreliable": (
                "这张图难以阅读，或该分子没有唯一的正确答案。当前答案未必被验证码接受，可依次尝试后续候选。"
            ),
            "ambiguous": "这张图包含每次都可能不同的随机答案。当前答案未必被验证码接受，可依次尝试后续候选。",
        },
        "geometry": (
            "碳原子距格线不足0.1像素，仅凭图像已无法判断它（们）的实际位置。当前答案未必被验证码接受，可依次尝试后续候选。"
        ),
        "grid_shift": "图中位于{looks_like}的碳原子被验证码判定在{cell}。你觉得你在{looks_like}吗？我觉得我在",
        "facts": "### 💡 你知道吗？",
        "on_line": "{first}和{second}之间的碳原子与格线重叠，验证码判定它在{cell}。",
        "near_line": "{first}和{second}之间的碳原子距格线不足{px}像素，验证码判定它在{cell}。",
        "star_cell": "星号位于{star}，但它标注的碳在{cell}。",
        "example_labels": {
            "01_baseline_352439_s_0": "对照组：普通样本",
            "02_baseline_star_off_cell_381327_s_0": "对照组：星号位于其他格子",
            "03_nondeterministic_123535_p_1": "真随机",
            "04_false_stereocentres_285955_p_1": "事实上没有手性碳的分子",
            "05_all_15_cells_177973_p_1": "大满贯",
            "06_illegible_overlap_497180_p_1": "绝对绝望样本",
            "07_tiny_font_194081_p_1": "盯帧-Hard",
            "08_extreme_aspect_16369_p_1": "盯帧-Lunatic",
            "09_grid_shift_191970_p_1": "盯帧一败涂地",
            "10_mixture_319851_p_1": "混合物",
        },
    },
    "en": {
        "intro": (
            "Upload the **original** image from Telegram (Save Image or Copy Image). Do not upload a screenshot or a resized copy.  \n"
            "About this captcha: [{site}]({article})"
        ),
        "upload": "Captcha",
        "hint": "Fill in the number from the captcha's “There should be X regions” for better accuracy",
        "force": "Try anyway",
        "reset": "Upload another",
        "recovery": "If rejected, view other candidates",
        "answer_image": "Answer",
        "previous": "Previous",
        "next": "Next candidate",
        "examples": "Examples: Ultra Despair Samples",
        "answer": "## Answer: {cells}",
        "candidate": "Candidate {index} of {count}",
        "added": "added {cells}",
        "removed": "removed {cells}",
        "change_separator": ", ",
        "changes": "Compared with the previous candidate: {changes} (green: added, red: removed)",
        "last": "This is the last candidate. If the captcha doesn't accept any of the candidates, please request a new one.",
        "gates": {
            "empty": (
                "### This is not a captcha image\n\n"
                "No chiral carbon was found in the image. Upload the original captcha image from Telegram."
            ),
            "not_original": (
                "### This doesn't look like the original\n\n"
                "It may be a screenshot or a thumbnail, or it was cropped or resized. The result may be wrong."
            ),
            "unreliable": (
                "### This answer is unreliable\n\n"
                "The image is hard to read, or the molecule has no single correct answer. "
                "We recommend you request a new captcha."
            ),
            "ambiguous": (
                "### This answer is True Random!\n\n"
                "This image has a random answer that changes every time. "
                "We recommend you request a new captcha."
            ),
        },
        "reminders": {
            "not_original": "This is not the original image. The answer may be wrong.",
            "unreliable": (
                "The image is hard to read, or the molecule has no single correct answer. "
                "The captcha may not accept this answer. Try the next candidates in order."
            ),
            "ambiguous": (
                "This image has a random answer that may change every time. "
                "The captcha may not accept this answer. Try the next candidates in order."
            ),
        },
        "geometry": (
            "A carbon atom is less than 0.1 px from a grid line. The image alone cannot tell which cell it is in. "
            "The captcha may not accept this answer. Try the next candidates in order."
        ),
        "grid_shift": "The carbon atom is drawn in {looks_like}, but the captcha places it in {cell}.",
        "facts": "### 💡 Did you know?",
        "on_line": (
            "The carbon atom between {first} and {second} overlaps the grid line. The captcha places it in {cell}."
        ),
        "near_line": (
            "The carbon atom between {first} and {second} is less than {px} px from the grid line. "
            "The captcha places it in {cell}."
        ),
        "star_cell": "The star is in {star}, but the carbon it marks is in {cell}.",
        "example_labels": {
            "01_baseline_352439_s_0": "Control: an ordinary one",
            "02_baseline_star_off_cell_381327_s_0": "Control: stars in another cell",
            "03_nondeterministic_123535_p_1": "True random",
            "04_false_stereocentres_285955_p_1": "No chiral carbon, in fact",
            "05_all_15_cells_177973_p_1": "Grand slam",
            "06_illegible_overlap_497180_p_1": "Ultra Despair Sample",
            "07_tiny_font_194081_p_1": "Pixel counting: Hard",
            "08_extreme_aspect_16369_p_1": "Pixel counting: Lunatic",
            "09_grid_shift_191970_p_1": "Not even Digital Foundry",
            "10_mixture_319851_p_1": "A mixture",
        },
    },
}
LANGUAGES = [("中文", "zh"), ("English", "en")]


def language_of(chosen: str | None, accepted: str) -> str:
    if chosen in TEXT:
        return chosen
    tags = (part.strip().lower() for part in accepted.split(","))
    return "zh" if any(tag.startswith("zh") for tag in tags) else "en"
