import re
from unicodedata import normalize

from app.knowledge import ProductKnowledge
from app.services.reply_rendering import ReplyTopic, render_business_reply


FACT_MARKERS = {
    "price": "[[PRICE_FACT]]",
    "trial": "[[TRIAL_FACT]]",
}
UNSUPPORTED_PROSE = re.compile(
    r"\d|[¥￥%％]"
    r"|[零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟]+"
    r"\s*(?:元|块|折|节|次|天|周|个月)"
    r"|免费|不收费|零元|折扣|优惠|退款|退费|保证|承诺|包学会|就业"
    r"|提供试听|支持试听|开放试听|有试听|可试听|可以试听|能试听|试听入口|试听名额"
    r"|适合零基础|课时|导师|助教|证书"
    r"|配套支持|学习支持|配套服务|答疑|辅导|带练|教学支持"
    r"|(?:我们|课程|平台|团队)[^。！？\n]{0,18}(?:提供|配备|安排|有配套|有支持)"
)


def render_model_reply_text(
    *,
    draft: str | None,
    product: ProductKnowledge,
    topics: list[ReplyTopic],
) -> str | None:
    if not draft or len(draft) > 320 or not topics:
        return None
    if set(topics) - FACT_MARKERS.keys():
        return None

    facts = {
        FACT_MARKERS[topic]: render_business_reply(product=product, topics=[topic])
        for topic in dict.fromkeys(topics)
    }
    lines = draft.splitlines()
    markers = [line.strip() for line in lines if line.strip() in facts]
    if len(markers) != len(facts) or set(markers) != facts.keys():
        return None

    prose = normalize("NFKC", "\n".join(line for line in lines if line.strip() not in facts))
    if "[" in prose or "]" in prose or UNSUPPORTED_PROSE.search(prose):
        return None
    if not any(char.isalpha() for char in prose):
        return None

    return "\n".join(facts.get(line.strip(), line) for line in lines)
