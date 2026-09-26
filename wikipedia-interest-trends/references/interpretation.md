# Interpreting results and writing recommendations

## From numbers to a recommendation

| Pattern in the output | What to say |
|---|---|
| `growing`, HIGH, `topic share of wiki YoY` also positive | Real, broad growth in interest. Strong candidate for validation. |
| `growing` but `topic share of wiki YoY` negative | The topic grows less than the whole wiki: interest is not really rising relative to overall usage. |
| topic growth positive, `topic share of wiki YoY` even higher | The whole wiki is shrinking (common since 2024); the topic gains share. Positive signal. |
| `stable`, HIGH | Mature, steady demand. Decide on size (`views/mo`) rather than momentum. |
| `inconclusive` / LOW | Not enough evidence either way. Recommend a longer period (`--months 36`) or a broader basket. |
| `new-article` | The article is new; growth cannot be measured yet. Report the current level only. |
| Big spike `event-like` | A news event; excluded from the trend. Mention it if the user cares about timing. |
| Big spike `bot-like` | Automated traffic removed; it would have faked growth. |
| Ranking robust (4/4 presets) | Recommend the top option clearly. |
| Ranking not robust | Present the trade-off: "if you prioritise growth -> X, if you prioritise size -> Y". |

Always pair a recommendation with a cheap validation step: a landing page or waitlist in that language,
search-keyword volumes, app-store keyword research, or a small ad test.

## Language editions are not markets

| Language | Caveat |
|---|---|
| en | Global lingua franca: readers come from the US, UK, India, Philippines, Nigeria, Europe... English interest does not mean an Anglophone market. |
| es | Spain plus all of Latin America (Mexico usually largest); check reader countries. |
| pt | Mostly Brazil; Portugal is much smaller. |
| fr | France, Belgium, Switzerland, Canada and Francophone Africa. |
| de | Germany, Austria, Switzerland. |
| ar | Many countries with very different markets. |
| zh | Wikipedia is blocked in mainland China; readers are mostly from Taiwan, Hong Kong and the diaspora. |
| ru | Readers from Russia, Ukraine, Belarus, Kazakhstan and elsewhere. Since 2022 many Ukrainians have moved from ru to uk Wikipedia, which shifts traffic between these two editions. |
| uk | Traffic has grown as users switched from Russian. Topic growth partly reflects that; check `topic share of wiki YoY`. |
| ko | Korean Wikipedia is small relative to speakers (Namuwiki is popular); volumes understate interest. |
| ja | Large and stable edition; Japanese readers use Wikipedia heavily. |
| hi, bn, ur, ta, ... | Many speakers read English Wikipedia; small volumes understate interest. |
| tr | Wikipedia was blocked in Turkey from 2017 to the end of 2019; avoid windows that include it. |
| fa | Access from Iran has been intermittently restricted; volumes partly reflect connectivity. |

## Topic basket ideas

Keep each basket to 2-5 articles with the same user intent. Give English titles; the tool maps them.

| Product question | Basket |
|---|---|
| Learning English | "English language", "English as a second or foreign language", "IELTS", "TOEFL" |
| Learning another language X | "X language", "X grammar", the main exam for X (for example "DELE" for Spanish, "JLPT" for Japanese) |
| Astronomy course | "Astronomy" (plus "Solar System", "Telescope" for a broader view) |
| Intermittent fasting / diet apps | "Intermittent fasting" (plus "Time-restricted eating" if it is a separate article) |
| Programming course | "Python (programming language)", "Computer programming" |
| Mental health / meditation app | "Meditation", "Mindfulness" |

Compare topics against each other only within the same language: absolute volumes across languages
differ by orders of magnitude, so use growth and `per million` for cross-language comparisons.

## Answer template (keep it short)

```
**Answer:** <one sentence with the verdict>.
- <finding 1 with numbers copied from the output>
- <finding 2>
- Confidence: <HIGH/MEDIUM/LOW> - <main reason / caveat>.
**Next step:** <one validation idea>. Caveat: Wikipedia pageviews measure curiosity, not purchase intent.
Files: <pdf / charts paths>
```

Ukrainian terms: зростання рік до року (YoY), довірчий інтервал (CI), відносно всієї Вікіпедії
(topic share of wiki YoY), довіра висока/середня/низька (confidence), сплески (spikes), кошик статей (basket).
