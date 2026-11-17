<script setup lang="ts">
// 指标说明: what the terms on these pages mean and how to read them, by section, with a search.
// Kept in step with how the pages work them out (web/server/market.py, the components).
import { computed, ref } from 'vue'
import InputText from 'primevue/inputtext'

interface Term { term: string; what: string; how?: string | string[] }   // a list reads as points
interface Section { id: string; title: string; intro?: string; terms: Term[] }

const SECTIONS: Section[] = [
  {
    id: 'table', title: '行情表格',
    intro: '行情页的每日全市场表格。A 股习惯红涨绿跌，本项目各处一致。',
    terms: [
      { term: '涨幅', what: '收盘价相对前一交易日收盘价的涨跌百分比（除权日按除权后的前收盘计算）。' },
      { term: '开盘涨幅', what: '开盘价相对前收盘的涨跌百分比。',
        how: '高开说明隔夜预期强；**高开低走（开盘涨幅大于涨幅）往往是获利盘出逃**，**低开高走则是承接有力**。' },
      { term: '振幅', what: '（最高价 − 最低价）÷ 前收盘，反映当天波动有多大。',
        how: '**振幅大而涨幅小，说明多空分歧大**；缩量小振幅多见于横盘整理。' },
      { term: '5日涨幅', what: '最近 5 个交易日逐日涨幅连乘得到的累计涨幅；停牌日按不涨不跌计。',
        how: '看短线强弱，配合当日涨幅可**区分「持续走强」和「一日游」**。' },
      { term: '成交量 / 成交额', what: '成交量以「手」计（1 手 = 100 股），成交额以元计（显示为万、亿）。',
        how: '**放量上涨说明资金认可**，**缩量上涨持续性存疑**；**放量下跌要警惕**。' },
      { term: '换手率', what: '成交量 ÷ 流通股本，表示当天有多少比例的流通股换了手。',
        how: '一般 **1%–3% 偏冷清**，**3%–10% 活跃**，**10% 以上为高度活跃或分歧剧烈**；小盘股、次新股天然偏高。' },
      { term: '主力净流入', what: '东方财富口径的当日大单与超大单净买入额。东方财富不可用时改用同花顺的资金净流入，表头会写明。',
        how: '是按成交单大小推算的估计值，**不是真实账户数据**；**看方向和持续性**，单日数字不必过度解读。' },
      { term: '市盈TTM', what: '总市值 ÷ 最近四个季度（滚动 12 个月）的归母净利润。亏损公司为负或不显示。',
        how: '**同行业内比较才有意义**；**周期股在景气高点市盈率反而最低**，需结合行业周期看。' },
      { term: '每股收益TTM', what: '最近四个季度的归母净利润 ÷ 总股本。' },
      { term: '总市值 / 流通值', what: '股价 × 总股本 / 股价 × 流通股本。',
        how: '流通值决定盘子大小：**流通值小的股票更容易被资金推动**，波动也更大。' },
      { term: '总股本 / 流通股', what: '公司发行的全部股份 / 其中可在二级市场交易的部分（不含限售股）。' },
      { term: '所属行业', what: '申万行业分类。一级行业约 31 个（如电子、食品饮料），二级行业更细（如半导体、白酒Ⅱ），名称后的「Ⅱ」是申万用来区分与一级同名的二级行业。' },
    ],
  },
  {
    id: 'limits', title: '涨跌停',
    intro: '行情页「涨停板」卡片。涨停、跌停、炸板家数由本项目按收盘价自行计算，可能与行情软件略有出入。',
    terms: [
      { term: '涨跌停幅度', what: '主板 10%，主板 ST 股 5%（2026-07-06 起改为 10%），创业板（300/301）与科创板（688/689）20%（创业板 2020-08-24 前为 10%），北交所 30%。新股上市初期不设涨跌幅，不计入。',
        how: '涨停价 = 前收盘 ×（1 + 幅度），沪深四舍五入到分，北交所向下截到分。' },
      { term: '涨停 / 跌停', what: '**收盘价等于涨停价 / 跌停价**。**盘中触及但收盘没封住的不算**。' },
      { term: '炸板', what: '盘中最高价触及涨停价，但收盘价低于涨停价，**即「封板失败」**。' },
      { term: '炸板率', what: '炸板 ÷（涨停 + 炸板）。',
        how: '衡量打板资金的成功率和情绪：**低于 20% 说明封板坚决、情绪好**；**超过 40% 说明追高资金被套，短线情绪转弱**。' },
      { term: '首板 / 连板 / 最高连板', what: '连续收盘涨停的交易日数：第一天为首板，连续 N 天为 N 连板；最高连板是当天所有涨停股中连板天数最多的。',
        how: '**最高连板高度是短线情绪的「温度计」**：高度不断抬升说明投机氛围浓，**高位股断板、高度下降往往是情绪退潮的信号**。' },
      { term: '连板天梯', what: '把当天涨停股按连板天数分层排列，最高的在上。',
        how: '看各层有多少只：**梯队完整（各高度都有）说明接力顺畅**；**只剩首板说明没有持续性**。' },
      { term: '涨停形态', what: '按当天开盘价与最低价判断。一字板：开盘即涨停且全天未打开；T字板：开盘涨停，盘中开板后又回封；换手板：盘中逐步拉升至涨停。',
        how: '**一字板筹码锁定最好、但几乎买不进**；**T字板说明有分歧但被承接**；**换手板经过充分换手，次日走势相对更健康**。' },
      { term: '涨停原因', what: '同花顺对该股涨停给出的题材标签，如「MicroLED+AI眼镜」。北交所股票没有。',
        how: '把同一题材的涨停股放在一起看，**能找出当天的主线题材**。' },
      { term: '首次 / 最后涨停时间', what: '第一次封上涨停的时刻，和最后一次（回封后）封住的时刻。09:25:00 表示集合竞价就涨停。',
        how: '**越早封板越强**；**首次与最后时间相差大，说明中途开过板**。跌停时间同理，越早跌停越弱。' },
      { term: '封单量 / 封单额', what: '收盘时挂在涨停价上的买单数量（手）和金额。来自同花顺，北交所来自东方财富。',
        how: '**封单额相对流通值越大封得越牢**，次日继续走强的概率越高；**只代表收盘那一刻**。' },
    ],
  },
  {
    id: 'stats', title: '市场统计',
    intro: '行情页表格下方的各统计卡片。',
    terms: [
      { term: '涨跌分布', what: '当天全部股票按涨跌幅分档计数：跌 >10%、7–10%、5–7%、3–5%、0–3%，平盘，涨 0–3% 至 >10%。',
        how: '比只看涨跌家数更细：**涨的多但大多在 0–3%，说明是弱反弹**；**两端（>7%）家数多说明分化剧烈**。' },
      { term: '历史涨跌趋势', what: '每天的上涨、下跌、平盘家数随时间的变化。',
        how: '上涨家数持续多于下跌家数说明行情普涨；反之是普跌，**即使指数没怎么跌**。' },
      { term: '赚钱效应（个股中位数）', what: '每天全部股票涨跌幅的中位数，即「排在正中间那只股票」的涨幅。',
        how: '比指数更能反映普通持股者的盈亏：**指数涨而中位数为负，说明多数人在亏钱**。' },
      { term: '上证指数', what: '上交所全部股票按市值加权，受银行、石油等大市值权重股影响大。' },
      { term: '沪深300', what: '沪深两市市值大、流动性好的 300 只股票，代表大盘蓝筹。' },
      { term: '中证500 / 中证1000', what: '排在沪深300 之后的 500 只（中盘）和再往后的 1000 只（小盘）股票。',
        how: '与沪深300 对比，可以**看出资金偏好大盘还是中小盘**。' },
      { term: '创业板指 / 创业板综', what: '创业板指为创业板中市值大、流动性好的 100 只；创业板综包含创业板全部股票。',
        how: '**创业板指强于创业板综，说明资金集中在龙头**；反之是中小创普涨。' },
      { term: '科创综指', what: '科创板全部股票，代表硬科技成长股。' },
      { term: '指数累计涨跌', what: '在「指数与腾落线」图中，各指数和个股中位数都从所选区间的前一个交易日收盘起算为 0%，便于同一起点比较。' },
      { term: '腾落线', what: '每天「上涨家数 − 下跌家数」逐日累加（平盘不计），从所选区间的前一交易日起算，**衡量涨跌是否普遍**。',
        how: [
          '正负：**为正说明区间内多数股票在涨，为负说明多数在跌**。',
          '**斜率比终值重要**：越陡普涨或普跌越强，走平是涨跌相抵。全市场约 5500 只，**单日 ±2000 以上即普涨或普跌**。',
          '对照指数：同涨同跌说明涨跌面广；**指数涨、腾落线跌，是少数权重股在撑，需警惕**；指数跌、腾落线平或涨，是多数股票抗跌。',
          '**只计家数不计涨幅**，涨跌幅度看「个股中位数」；不同区间起点不同，**数值不能横比**。',
        ] },
      { term: '市场成交额', what: '沪深京全部 A 股当天成交额之和（元，显示为亿、万亿）。',
        how: '量是价的先行指标：**放量上涨说明增量资金入场，缩量上涨难持续**；成交额持续萎缩常见于行情末期或底部。' },
    ],
  },
  {
    id: 'industry', title: '行业涨跌榜',
    terms: [
      { term: '平均涨幅', what: '行业内全部股票当天涨幅的简单平均（等权），不按市值加权。' },
      { term: '中位涨幅', what: '行业内股票涨幅的中位数。',
        how: '**平均涨幅明显高于中位涨幅，说明是少数个股大涨拉高了平均**。' },
      { term: '5日涨幅', what: '行业内股票 5 日涨幅的简单平均。', how: '看行业的短线持续性，配合当日涨幅找出连续走强的板块。' },
      { term: '上涨占比', what: '行业内当天上涨的股票占比。', how: '**高于 70% 说明板块普涨**，是真正的板块行情。' },
      { term: '成交额 / 成交占比', what: '行业内股票成交额之和，及其占全市场成交额的比例。',
        how: '**成交占比持续上升说明资金在向该行业集中**。' },
      { term: '领涨', what: '行业内当天涨幅最大的股票及其涨幅。' },
    ],
  },
  {
    id: 'kline', title: 'K线与技术指标',
    intro: '个股页的 K 线图。**价格为不复权价**，除权除息日会出现跳空，**不代表真实涨跌**。',
    terms: [
      { term: 'K线', what: '每根蜡烛表示一个交易日的开盘、收盘、最高、最低价。收盘高于开盘为阳线（红），反之为阴线（绿）；上下影线是当天到过的最高、最低价。',
        how: '**长上影线说明上方抛压重，长下影线说明下方有承接**。' },
      { term: '均线 MA', what: '过去 N 个交易日收盘价的平均，图中有 MA5、10、20、60、144、233。',
        how: '短期均线在长期均线之上并向上发散为**多头排列**，反之为**空头排列**；股价站上或跌破 MA20、MA60 常被视为中期转强或转弱。' },
      { term: '成交量 VOL', what: '每天的成交量柱（手），以及 5、10、20 日均量线。', how: '量能高于均量说明放量，结合价格涨跌看资金态度。' },
      { term: 'MACD', what: 'DIF = 12 日 EMA − 26 日 EMA；DEA = DIF 的 9 日 EMA；柱 = 2 ×（DIF − DEA）。参数可在图中修改。',
        how: 'DIF 上穿 DEA 为**金叉**、下穿为**死叉**；**零轴之上偏多、之下偏空**；价格创新高而 MACD 不创新高为**顶背离**，是动能衰竭的信号。' },
      { term: 'KDJ', what: '用 9 日内最高、最低价衡量收盘价的相对位置，得到 K、D、J 三条线（参数 9、3、3）。',
        how: '**K、D 高于 80 为超买、低于 20 为超卖**；J 线最敏感。强势股可以长时间钝化在超买区，**不宜单独作为卖出依据**。' },
      { term: 'RSI', what: '相对强弱指数，N 日内上涨幅度占总波动的比例（0–100），默认 6、12、24 日三条。',
        how: '**高于 70–80 超买、低于 20–30 超卖**；短周期上穿长周期为转强。' },
      { term: '缺口', what: '相邻两根 K 线之间没有成交的价格区间：今天最低价高于昨天最高价为向上缺口，反之为向下缺口。图中以灰色带标出近半年的缺口，可隐藏。',
        how: '**向上缺口常成为支撑、向下缺口常成为压力**；**缺口被回补说明原有趋势减弱**。' },
    ],
  },
  {
    id: 'analysis', title: 'AI 分析',
    intro: '分析页由多个 AI 角色协作完成一份研究报告，**结论仅供参考，不构成投资建议**。',
    terms: [
      { term: '分析师', what: '市场/技术分析师看价格与技术指标；情绪分析师看市场情绪与资金；新闻分析师看公司与宏观新闻；基本面分析师看财务与估值。可按需勾选。' },
      { term: '多空辩论', what: '看多与看空研究员根据分析师报告轮流辩论，再由研究经理给出投资计划。' },
      { term: '风控讨论', what: '激进、中性、保守三类风控角色评估交易员的方案，最后给出决策。' },
      { term: '研究深度', what: '辩论与风控讨论的轮数：浅 1 轮、中 3 轮、深 5 轮。',
        how: '**轮数越多观点越充分，但耗时和模型费用也越高**。' },
      { term: '深度思考 / 快速思考模型', what: '深度思考模型用于研究经理、最终决策等需要综合判断的环节；快速思考模型用于分析师、辩论与风控讨论等其余环节。',
        how: '深度思考模型决定结论质量，可选更强的模型；快速思考模型调用次数多，选便宜快速的即可。' },
    ],
  },
]

// Text marks its key points as **…**; they are drawn bold (no HTML from the text).
function parts(text: string): { t: string; b: boolean }[] {
  return text.split(/\*\*(.+?)\*\*/).map((t, i) => ({ t, b: i % 2 === 1 })).filter((x) => x.t)
}
const plain = (text: string) => text.replace(/\*\*/g, '')

const q = ref('')
const shown = computed(() => {
  const k = q.value.trim().toLowerCase()
  if (!k) return SECTIONS
  return SECTIONS.map((s) => ({
    ...s,
    terms: s.terms.filter((t) => plain(`${t.term} ${t.what} ${[t.how ?? ''].flat().join(' ')}`).toLowerCase().includes(k)),
  })).filter((s) => s.terms.length)
})
const count = computed(() => shown.value.reduce((a, s) => a + s.terms.length, 0))

function jump(id: string) {
  document.getElementById(`g-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <div class="page guide">
    <div class="card head">
      <div>
        <h2>指标说明</h2>
        <p class="muted small">本项目各页面用到的名词是什么、怎么看。</p>
      </div>
      <InputText v-model="q" class="search" placeholder="搜索名词，如 炸板、腾落线" size="small" />
    </div>
    <nav class="toc">
      <button v-for="s in shown" :key="s.id" type="button" class="chip" @click="jump(s.id)">
        {{ s.title }} <span class="muted">{{ s.terms.length }}</span>
      </button>
    </nav>
    <p v-if="!count" class="muted">没有找到「{{ q }}」相关的名词。</p>
    <section v-for="s in shown" :id="`g-${s.id}`" :key="s.id" class="card sec">
      <h3>{{ s.title }}</h3>
      <p v-if="s.intro" class="muted small intro"><template v-for="(x, j) in parts(s.intro)" :key="j"><b v-if="x.b">{{ x.t }}</b><template v-else>{{ x.t }}</template></template></p>
      <dl>
        <template v-for="t in s.terms" :key="t.term">
          <dt>{{ t.term }}</dt>
          <dd>
            <p><span class="tag">是什么</span><template v-for="(x, j) in parts(t.what)" :key="j"><b v-if="x.b">{{ x.t }}</b><template v-else>{{ x.t }}</template></template></p>
            <template v-if="Array.isArray(t.how)">
              <p><span class="tag how">怎么看</span></p>
              <ul class="points"><li v-for="h in t.how" :key="h"><template v-for="(x, j) in parts(h)" :key="j"><b v-if="x.b">{{ x.t }}</b><template v-else>{{ x.t }}</template></template></li></ul>
            </template>
            <p v-else-if="t.how"><span class="tag how">怎么看</span><template v-for="(x, j) in parts(t.how)" :key="j"><b v-if="x.b">{{ x.t }}</b><template v-else>{{ x.t }}</template></template></p>
          </dd>
        </template>
      </dl>
    </section>
  </div>
</template>

<style scoped>
.guide { max-width: 980px; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
h2 { margin: 0; font-size: 18px; }
h3 { margin: 0 0 4px; font-size: 16px; }
.small { font-size: 12px; }
.head p { margin: 4px 0 0; }
.search { width: 240px; max-width: 100%; }
.toc { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.chip { font: inherit; font-size: 13px; padding: 4px 12px; border: 1px solid var(--border); border-radius: 14px;
        background: #fff; color: inherit; cursor: pointer; }
.chip:hover { border-color: var(--up); }
.sec { margin-bottom: 12px; scroll-margin-top: 12px; }
.intro { margin: 0 0 8px; }
dl { margin: 0; display: grid; grid-template-columns: 150px 1fr; }
dt, dd { padding: 10px 0; border-top: 1px solid var(--border); }
dt { font-weight: 600; font-size: 14px; padding-right: 12px; }
dd { margin: 0; font-size: 13px; line-height: 1.7; }
dd p { margin: 0; }
dd p + p { margin-top: 4px; }
dd b, .intro b { font-weight: 600; color: #1f2933; }
.points { margin: 2px 0 0; padding-left: 18px; }
.tag { display: inline-block; font-size: 11px; line-height: 1.5; padding: 0 6px; margin-right: 8px; border-radius: 4px;
       background: #f1f3f6; color: var(--muted); }
.tag.how { background: #fdecec; color: var(--up); }
@media (max-width: 640px) {
  dl { grid-template-columns: 1fr; }
  dt { padding-bottom: 0; }
  dd { border-top: 0; padding-top: 4px; }
}
</style>
