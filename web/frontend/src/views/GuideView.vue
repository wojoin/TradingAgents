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
      { term: '空间板高度', what: '每天涨停股中**连续涨停天数最多**的那只（空间板）的板数，以及连板（2板及以上）家数，随时间画成曲线。',
        how: '短线**情绪周期**的主线：**高度不断抬升是发酵期**，**高度骤降、龙头断板是退潮期**，长期在 2–3 板徘徊是冰点；冰点后重新出现高标常是新周期的起点。' },
      { term: '主线题材', what: '把每只涨停股的涨停原因（同花顺）按「+」拆成题材，统计近 3/5/10 个交易日每天各题材的涨停家数。',
        how: '**连续多日都有涨停、家数还在增加的题材是主线**；只出现一天的多为一日游；主线题材家数开始减少，说明炒作进入尾声。' },
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
      { term: '情绪综合分', what: '把**涨跌比、涨停跌停比、封板率、涨停溢价、晋级率、空间板**六项各折算成 0–100 后取平均：比例类直接用百分比，涨停溢价 −5%→0、+5%→100，晋级率 40% 及以上为 100，空间板 1 板为 0、8 板及以上为 100。',
        how: '**≥80 过热**（追高风险大）、60–80 活跃、40–60 中性、20–40 低迷、**<20 冰点**（冰点后回升常是短线机会）。各项等权，仅作参考，宜结合各分项看是哪一项拖累或拉动。' },
      { term: '龙虎榜', what: '交易所公布的当日异动股票（涨跌幅偏离、换手率过高等）及买卖金额最大的营业部席位，收盘后约 18:00 公布；本页列出席位净买、机构净买和上榜原因。',
        how: '**机构大额净买多被视为认可**，**游资席位集中买入多为短线炒作**；净买额占成交比越高，席位的影响越大。次日走势还要看市场情绪，不宜单凭上榜追买。' },
      { term: '涨停溢价', what: '昨日收盘涨停的股票今天的**平均涨跌幅**，以及其中上涨的占比。',
        how: '短线情绪最直接的指标：**为正说明追涨停能赚钱**、情绪好；**持续为负说明打板亏钱**，情绪退潮，宜降低短线仓位。' },
      { term: '连板晋级率', what: '昨日涨停的股票今天**再次涨停的比例**：首板→2板、2板→3板、3板以上再晋级，以及连板（2板及以上）整体。',
        how: '晋级率高说明接力资金积极、连板容易走出来；**高位晋级率骤降常是情绪见顶的信号**。首板晋级率一般在 20%–30%，明显高于此为强势。' },
      { term: '大小盘风格', what: '每天按流通市值排名分档：**大盘前 300（≈沪深300）、中盘 301–800（≈中证500）、小盘 801–1800（≈中证1000）、微盘最小 400**，不含 ST，统计各档股票涨幅的中位数并累计。日线快照之前的市值按当日收盘价 × 最新流通股本估算。',
        how: '**哪条线在上，资金就偏好哪类股票**：大盘领先多见于防御或权重行情，小盘、微盘领先说明题材和投机活跃。风格切换往往持续一段时间。' },
      { term: '新高新低', what: '收盘价（复权）**高于此前 59 个交易日每天收盘**的为 60 日新高，低于的为新低；250 日（约 52 周）同理。上市不满所需天数的不计。',
        how: '**新高多于新低说明市场在走强**；**指数创新高而新高家数减少，是上涨面收窄的警示**；新低家数见顶回落常出现在底部区域。' },
      { term: '均线上方占比', what: '收盘价（复权）**高于自身 20 日、60 日均线的股票占比**。',
        how: '**高于 80% 偏热、低于 20% 超跌**；20 日线反映短期，60 日线反映中期。从 20% 以下回升并站上 50%，常是行情转强的确认。' },
      { term: '股债性价比', what: '申万A指的**盈利收益率（1 ÷ 市盈率）减去 10 年期国债收益率**，即买股票比买国债多得的风险溢价，也叫 ERP。',
        how: '**分位越高股票相对债券越便宜**：历史上 **≥80% 分位多对应市场底部区域**，**≤20% 多对应顶部区域**。利率下行时同样的市盈率更有吸引力，所以比单看市盈率更全面；适合判断长期位置，不适合短线择时。' },
      { term: '全市场估值', what: '申万A指（覆盖全部 A 股，市值加权）每天的市盈率、市净率和股息率，2005 年至今；分位为当前值在所选区间（近 1/3/5/10 年或全部）中的位置。',
        how: '**市盈率、市净率分位越低越便宜，股息率相反**。**低于 20% 分位常是长期布局的区域，高于 80% 要控制仓位**。估值适合判断长期位置，**不适合短线择时**：便宜可以更便宜，贵也可以更贵。' },
      { term: '市场资金流', what: '东方财富全市场主力（超大单 + 大单）净流入及其占成交额的比例，另列超大单、大单、中单、小单分项，近约 120 个交易日。',
        how: '按成交单大小推算，不是真实账户数据。**主力持续净流出而小单净流入，常是机构派发、散户接盘**；主力由持续流出转为流入，是资金回流的信号。' },
      { term: '市场波动率（QVIX）', what: '50ETF 期权的隐含波动率，即中国版「恐慌指数」VIX，2015 年至今；一般滞后一个交易日。',
        how: '**急升说明市场恐慌**，常出现在急跌的末段，恐慌见顶往往接近短期底部；**长期处于极低位说明过度平静**，要警惕突然的大波动。' },
      { term: '限售解禁', what: '未来 30 天每天到期可以卖出的限售股市值（东方财富），以及解禁市值最大的个股和占解禁前流通市值的比例。',
        how: '**解禁市值大、占流通市值比例高（≥10%）的个股，解禁前后往往承压**；全市场解禁集中的日子整体也易受影响。实际是否减持要看股东意愿，首发原股东、定增解禁通常压力更大。' },
      { term: '两融余额', what: '沪深两市融资（借钱买股）与融券（借股卖出）的未还余额之和。交易所次日公布，所以最新一般是前一交易日。',
        how: '反映**杠杆资金**多少：**余额持续增加说明加杠杆做多**；**单日大幅减少常是去杠杆、被动平仓**，会放大下跌。余额与指数背离（指数涨而余额降）说明杠杆资金不认可。' },
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
      { term: '行业轮动热力图', what: '申万一级行业指数（申万官方，**市值加权**）最近 10 或 20 个交易日每天的涨跌幅，按区间累计涨幅排序；红涨绿跌，颜色越深幅度越大。',
        how: '**连续变红的行业是资金正在流入的方向**；一行由红转绿、另一行由绿转红，说明**资金在轮动切换**。所有行业同时变红或变绿是普涨普跌，不是轮动。' },
      { term: '行业拥挤度', what: '申万一级行业近 5 日平均的**成交额占比**和**换手率**，各自在 2021 年以来每天同样 5 日平均中的分位，两者平均即拥挤度（0–100）。',
        how: '**≥80 为拥挤**：交易过热、资金一致性高，**易出现快速回撤**，尤其是 20 日涨幅已经很大的行业；拥挤但在下跌说明资金正在出逃。**≤20 为冷清**：关注度低，可能被低估或正被遗弃。拥挤度描述的是交易热度，不是方向。' },
      { term: '行业估值分位', what: '行业当前市盈率（PE）、市净率（PB）在 2021 年以来每天数值中的位置：分位 30% 表示历史上有 30% 的日子比现在更便宜或一样。',
        how: '**分位 ≤20% 偏便宜，≥80% 偏贵**。**不同行业估值水平天然不同**（银行 PE 常年个位数，科技股几十倍），所以**看分位而非绝对值**；周期行业在景气高点 PE 反而低，宜结合 PB 看。' },
      { term: '股息率', what: '过去 12 个月现金分红 ÷ 市值。',
        how: '**股息率越高越便宜**，高股息行业（银行、公用事业等）在市场低迷时更抗跌。' },
      { term: '行业资金流', what: '各股主力净流入（东方财富）按申万行业求和，可看当日、近 5 日、近 10 日，列出净流入、净流出最多的各 10 个行业。**只有最近一个交易日能取到**。',
        how: '与热力图配合看：**涨且资金净流入是真强势**；涨而资金净流出，可能是拉高出货。' },
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

// 行情统计一览: every card on the 行情 page, by category and group in the page's order.
interface StatItem { item: string; what: string; how: string; purpose: string; key?: boolean }   // key: look at it first
interface StatGroup { group: string; items: StatItem[] }
interface StatCategory { category: string; groups: StatGroup[] }
const STATS: StatCategory[] = [
  {
    category: '一、市场全景', groups: [
      { group: '今日涨跌', items: [
        { item: '涨跌分布', what: '全部股票按涨跌幅分 11 档的家数（跌 >10% … 涨 >10%）', how: '涨的多但集中在 0–3% 是**弱反弹**；两端（>7%）家数多说明**分化剧烈**', purpose: '判断今天是**普涨普跌还是结构行情**' },
        { item: '赚钱效应', key: true, what: '每天全部股票涨跌幅的**中位数**', how: '指数涨而中位数为负，说明**多数人在亏钱**', purpose: '看普通持股者的真实盈亏' },
        { item: '历史涨跌趋势', what: '每天上涨、下跌、平盘家数随时间变化', how: '上涨家数持续多于下跌家数是普涨，反之普跌', purpose: '看涨跌面的持续性' },
      ] },
      { group: '指数与量能', items: [
        { item: '指数与腾落线', what: '7 个指数与个股中位数的区间累计涨跌；腾落线为每天「上涨 − 下跌家数」累加', how: '指数涨、腾落线跌，是**少数权重股在撑**，需警惕', purpose: '识别**指数失真**' },
        { item: '市场成交额', key: true, what: '沪深京全部 A 股每天成交额之和', how: '**放量上涨**说明增量资金入场；**缩量上涨难持续**', purpose: '判断资金热度与行情能否持续' },
      ] },
      { group: '资金与风险', items: [
        { item: '市场资金流', what: '全市场主力（超大单 + 大单）净流入，及超大单、大单、中单、小单分项（近 120 日）', how: '**主力流出而小单流入常是机构派发、散户接盘**；主力由流出转流入是回流信号', purpose: '看大资金的进出方向' },
        { item: '两融余额', what: '沪深融资融券未还余额及每日变化（次日公布）', how: '余额持续增加是**加杠杆做多**；单日大幅减少常是**被动平仓**', purpose: '看杠杆资金的进出' },
        { item: '市场波动率（QVIX）', what: '50ETF 期权隐含波动率，中国版恐慌指数，及 2015 年以来分位', how: '**急升是恐慌，常在急跌末段**；长期极低说明过度平静，警惕突变', purpose: '衡量**市场恐慌程度**' },
        { item: '限售解禁', what: '未来 30 天每天的解禁市值，及解禁市值最大的个股和占流通市值比例', how: '**解禁市值大、占流通比例高的个股**解禁前后易承压', purpose: '预判**筹码供给压力**' },
      ] },
    ],
  },
  {
    category: '二、短线情绪', groups: [
      { group: '情绪温度', items: [
        { item: '情绪综合分', key: true, what: '涨跌比、涨停跌停比、封板率、涨停溢价、晋级率、空间板六项各折算 0–100 后平均', how: '**≥80 过热、<20 冰点**；冰点后回升常是短线机会', purpose: '**一个数看懂当天短线情绪**' },
      ] },
      { group: '涨停板', items: [
        { item: '涨停、跌停与炸板', what: '收盘涨停、跌停的股票明细，盘中触及涨停却没封住的炸板，及炸板率', how: '炸板率 **<20% 情绪好、>40% 转弱**；一字板、早封板更强', purpose: '看当天打板资金的强弱' },
        { item: '连板天梯', what: '涨停股按连续涨停天数分层', how: '**梯队完整**说明接力顺畅；只剩首板说明没有持续性', purpose: '看短线接力的结构' },
      ] },
      { group: '主线题材', items: [
        { item: '主线题材', what: '涨停原因（同花顺）按「+」拆成题材，统计近 3/5/10 日每天的涨停家数', how: '**连续多日都有涨停的题材是主线**；只出现一天多为一日游', purpose: '找出**当前市场主线**' },
      ] },
      { group: '情绪指标', items: [
        { item: '涨停溢价', key: true, what: '昨日涨停股今天的平均涨跌幅和上涨占比', how: '**为正追涨停能赚钱**；持续为负说明打板亏钱、情绪退潮', purpose: '短线情绪**最直接的温度计**' },
        { item: '连板晋级率', what: '昨日涨停股今天再涨停的比例（首板→2板、连板整体等）', how: '晋级率高说明接力积极；**高位晋级率骤降常是见顶信号**', purpose: '看接力资金的强度' },
        { item: '空间板高度', key: true, what: '每天最高连板的板数和连板家数', how: '**高度抬升是发酵期，骤降是退潮期**，2–3 板徘徊是冰点', purpose: '判断**短线情绪周期**所处阶段' },
        { item: '涨停跌停趋势', what: '每天涨停、跌停、炸板家数随时间变化', how: '涨停持续多于跌停说明情绪偏暖；跌停激增是恐慌', purpose: '看短线情绪的历史走势' },
      ] },
      { group: '龙虎榜', items: [
        { item: '龙虎榜', what: '当日异动上榜股票、席位买卖金额、机构净买及上榜原因', how: '**机构大额净买多为认可**，游资集中买入多为短线炒作', purpose: '看**主力席位在买什么**' },
      ] },
    ],
  },
  {
    category: '三、板块与资金', groups: [
      { group: '行业表现', items: [
        { item: '行业涨跌榜', what: '申万一级/二级行业的平均、中位涨幅，5 日涨幅，上涨占比，成交占比，领涨股', how: '**上涨占比 >70% 是真正的板块行情**；平均远高于中位说明少数股拉动', purpose: '找出当天最强、最弱的行业' },
        { item: '行业资金流', what: '主力净流入按申万行业求和，当日 / 5日 / 10日的净流入、净流出前 10（仅最近一个交易日）', how: '**多日持续净流入比单日可靠**；涨而净流出可能是拉高出货', purpose: '看资金流向哪些行业' },
      ] },
      { group: '行业轮动', items: [
        { item: '行业轮动热力图', key: true, what: '31 个申万一级行业近 10/20 日每天的涨跌幅，按区间累计排序', how: '**连续变红是资金流入方向**；一行转绿、另一行转红是轮动切换', purpose: '把握**板块轮动节奏**' },
        { item: '行业拥挤度', what: '各行业近 5 日平均成交额占比和换手率，在 2021 年以来历史中的分位，两者平均为拥挤度', how: '**≥80 拥挤，易快速回撤**，尤其是已大涨的行业；≤20 冷清，关注度低', purpose: '识别**交易过热的板块风险**' },
      ] },
    ],
  },
  {
    category: '四、市场宽度与风格', groups: [
      { group: '市场宽度', items: [
        { item: '新高新低', key: true, what: '收盘创 60 日、250 日新高、新低的家数（复权价）', how: '新高多于新低是走强；**指数新高而新高家数减少是上涨面收窄**', purpose: '确认趋势的广度' },
        { item: '均线上方占比', what: '站上 20 日、60 日均线的股票占比', how: '**>80% 偏热，<20% 超跌**', purpose: '判断市场整体超买超卖' },
      ] },
      { group: '风格', items: [
        { item: '大小盘风格', what: '按流通市值分大盘、中盘、小盘、微盘四档，各档中位涨幅的累计', how: '**哪条线在上，资金就偏好哪类股票**', purpose: '判断**大盘还是小盘占优**' },
      ] },
    ],
  },
  {
    category: '五、估值', groups: [
      { group: '估值', items: [
        { item: '全市场估值', what: '申万A指 2005 年至今的市盈率、市净率、股息率及分位', how: '**分位越低越便宜**（股息率相反）；<20% 常是长期布局区域', purpose: '判断市场的**长期位置**' },
        { item: '股债性价比', key: true, what: '盈利收益率（1 ÷ 市盈率）减 10 年国债收益率', how: '**分位越高股票相对债券越便宜**，≥80% 多对应底部区域', purpose: '比较**股票与债券谁更划算**' },
        { item: '行业估值', what: '申万一级行业的市盈率、市净率、股息率及 2021 年以来分位', how: '**看分位而非绝对值**；≤20% 偏便宜，≥80% 偏贵', purpose: '找出相对便宜或过热的行业' },
      ] },
    ],
  },
]

const q = ref('')
const shown = computed(() => {
  const k = q.value.trim().toLowerCase()
  if (!k) return SECTIONS
  return SECTIONS.map((s) => ({
    ...s,
    terms: s.terms.filter((t) => plain(`${t.term} ${t.what} ${[t.how ?? ''].flat().join(' ')}`).toLowerCase().includes(k)),
  })).filter((s) => s.terms.length)
})
const count = computed(() => shown.value.reduce((a, s) => a + s.terms.length, 0) + statRows.value.length)

// The table's rows (filtered by the search), with how many rows each category and group cell spans.
const statRows = computed(() => {
  const k = q.value.trim().toLowerCase()
  const rows: (StatItem & { category: string; group: string; catSpan: number; grpSpan: number })[] = []
  for (const c of STATS) {
    const catStart = rows.length
    for (const g of c.groups) {
      const items = g.items.filter((i) => !k || plain(`${c.category} ${g.group} ${i.item} ${i.what} ${i.how} ${i.purpose}`).toLowerCase().includes(k))
      items.forEach((i, n) => rows.push({ ...i, category: c.category, group: g.group, catSpan: 0, grpSpan: n === 0 ? items.length : 0 }))
    }
    if (rows.length > catStart) rows[catStart].catSpan = rows.length - catStart
  }
  return rows
})

function jump(id: string) {
  document.getElementById(`g-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
</script>

<template>
  <div class="page guide">
    <div class="card head">
      <div>
        <h2>指标说明</h2>
        <p class="muted small">行情页统计一览，以及本项目各页面用到的名词是什么、怎么看。</p>
      </div>
      <InputText v-model="q" class="search" placeholder="搜索名词，如 炸板、腾落线" size="small" />
    </div>
    <nav class="toc">
      <button v-if="statRows.length" type="button" class="chip" @click="jump('stats')">
        行情统计一览 <span class="muted">{{ statRows.length }}</span>
      </button>
      <button v-for="s in shown" :key="s.id" type="button" class="chip" @click="jump(s.id)">
        {{ s.title }} <span class="muted">{{ s.terms.length }}</span>
      </button>
    </nav>
    <p v-if="!count" class="muted">没有找到「{{ q }}」相关的名词。</p>
    <section v-if="statRows.length" id="g-stats" class="card sec">
      <h3>行情统计一览</h3>
      <p class="muted small intro">行情页下方的全部统计，按页面上的类别、分组和顺序排列，越靠前越重要。<span class="key">红色</span>为每个类别中最该重点看的项目，时间有限时先看它们。各名词的详细解释见下方各节。</p>
      <div class="stat-wrap">
        <table class="stat-table">
          <thead>
            <tr><th>类别</th><th>分组</th><th>统计项</th><th>统计什么</th><th>怎么看</th><th>用途</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in statRows" :key="`${r.group}-${r.item}`">
              <td v-if="r.catSpan" :rowspan="r.catSpan" class="merged cat">{{ r.category }}</td>
              <td v-if="r.grpSpan" :rowspan="r.grpSpan" class="merged">{{ r.group }}</td>
              <td class="item" :class="{ key: r.key }">{{ r.item }}<span v-if="r.key" class="star">重点</span></td>
              <td><template v-for="(x, j) in parts(r.what)" :key="j"><b v-if="x.b">{{ x.t }}</b><template v-else>{{ x.t }}</template></template></td>
              <td><template v-for="(x, j) in parts(r.how)" :key="j"><b v-if="x.b">{{ x.t }}</b><template v-else>{{ x.t }}</template></template></td>
              <td><template v-for="(x, j) in parts(r.purpose)" :key="j"><b v-if="x.b">{{ x.t }}</b><template v-else>{{ x.t }}</template></template></td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
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
.guide { max-width: 1240px; }
.stat-wrap { overflow-x: auto; }
.stat-table { width: 100%; border-collapse: collapse; font-size: 13px; line-height: 1.6; min-width: 900px; }
.stat-table th, .stat-table td { border: 1px solid var(--border); padding: 7px 10px; vertical-align: middle; text-align: left; }
.stat-table th { background: #f6f7f9; font-weight: 600; white-space: nowrap; }
.stat-table .merged { text-align: center; font-weight: 600; white-space: nowrap; background: #fafbfc; }
.stat-table .item { font-weight: 600; white-space: nowrap; }
.stat-table b { font-weight: 600; color: #1f2933; }
.stat-table .item.key, .intro .key { color: var(--up); }
.star { margin-left: 6px; font-size: 11px; font-weight: 500; padding: 0 5px; border-radius: 4px; background: #fdecec; color: var(--up); }
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
