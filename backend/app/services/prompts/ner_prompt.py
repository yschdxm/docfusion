NER_PROMPT = """从以下文本中提取所有实体和关系。这是一个全领域文档，可能涉及任意学科和行业。

文本：{text}

实体类型（根据文本内容动态选择最匹配的类型，不要强行归类）：

通用：Person(人名) Organization(机构) Department(部门) Location(地名) GeographicFeature(地理实体) Date(日期) Duration(时长) TimePeriod(时期) Money(金额) Percentage(百分比) Measurement(度量值) Count(数量) Ranking(排名) Law(法律) Policy(政策) Standard(标准) Contract(合同) Event(事件) Material(物料) Product(产品) Technology(技术) Software(软件/平台) Equipment(设备) AnimalSpecies(动物) PlantSpecies(植物) Food(食品) Nutrient(营养成分)
医疗健康：Disease(疾病) Symptom(症状) Drug(药品) Treatment(治疗方案) MedicalDevice(医疗器械) BodyPart(身体部位) BodySystem(人体系统) Gene(基因) Virus(病毒/病原体) Vaccine(疫苗) MedicalTest(检查项目) HealthIndicator(健康指标) Hospital(医院) MedicalDepartment(科室) TraditionalMedicine(中医药) MentalHealthCondition(心理状况)
气象环境：WeatherEvent(气象事件) ClimateIndicator(气候指标) Pollutant(污染物) EmissionSource(排放源) EcologicalZone(生态区域) Disaster(灾害) EnvironmentalStandard(环境标准) WaterBody(水体) ForestResource(森林资源) SoilType(土壤) AirQualityLevel(空气质量等级)
经济金融：Industry(行业) EconomicIndicator(经济指标) FinancialProduct(金融产品) StockCode(股票代码) Currency(货币) TradeAgreement(贸易协定) TaxType(税种) InvestmentProject(投资项目) SupplyChain(供应链)
交通运输：TransportRoute(交通线路) Vehicle(交通工具) TransportHub(交通枢纽) Infrastructure(基础设施) TransportIndicator(交通指标)
能源矿产：EnergySource(能源) PowerPlant(电站) Mine(矿山) MineralResource(矿产) EnergyIndicator(能源指标)
农业：Crop(农作物) Farmland(农田) AgriculturalProduct(农产品) Fertilizer(肥料) FarmingTechnique(农艺技术) Livestock(畜牧) FisheryResource(渔业资源) AgriculturalMachinery(农机) AgriculturalIndicator(农业指标)
水利：WaterProject(水利工程) WaterResource(水资源) FloodControlMeasure(防洪设施) WaterQualityIndicator(水质指标)
教育：School(学校) Major(专业) Course(课程) Certification(证书) Exam(考试) EducationLevel(学段) ResearchProject(科研课题) AcademicPaper(学术论文) Scholar(学者) ResearchInstitution(科研院所)
文旅：ScenicSpot(景点) CulturalRelic(文物) ArtWork(作品) Festival(节庆) Route(线路) CulturalVenue(文化场馆) IntangibleHeritage(非遗) FolkCustom(民俗)
体育：SportEvent(体育赛事) Athlete(运动员) SportsTeam(运动队) SportVenue(体育场馆) SportRecord(体育记录)
国防军事：MilitaryUnit(军事单位) WeaponSystem(武器装备) MilitaryOperation(军事行动) DefenseProject(国防工程)
法律司法：CourtCase(案件) Court(法院) LegalTerm(法律概念) Penalty(处罚) LegalProcedure(法律程序)
社会民生：SocialProgram(社会项目) WelfareBenefit(福利补贴) PopulationGroup(特定人群) Community(社区)
科技信息：Patent(专利) TechStandard(技术标准) Innovation(创新成果) DataResource(数据资源) Algorithm(算法)
建筑规划：Building(建筑物) UrbanPlan(城市规划) ConstructionProject(在建工程) ArchitecturalStyle(建筑风格)
食品卫生：FoodSafetyStandard(食安标准) FoodAdditive(食品添加剂) NutritionLabel(营养标签) FoodContaminant(食品污染物)

关系类型（按语义分类，选择最匹配的）：
- 归属：BELONGS_TO, SUBORDINATE_TO, MEMBER_OF, HOLDS_POSITION
- 空间：LOCATED_IN, ADJACENT_TO, CONTAINS, HEADQUARTERED_IN, IMPLEMENTED_IN, CONNECTS
- 医疗：HAS_SYMPTOM, TREATED_BY, CAUSES, AFFECTS, HAS_SIDE_EFFECT, INTERACTS_WITH, CONTRAINDICATED_FOR, DIAGNOSES, PREVENTS, ASSOCIATED_WITH
- 经济：UPSTREAM_OF, DOWNSTREAM_OF, OPERATES_IN, FUNDED_BY, PRODUCED_BY, PRODUCED_IN, BELONGS_TO_INDUSTRY, BETWEEN
- 气象环境：EMITTED_BY, EXCEEDS, RICH_IN, HAS_CLIMATE, DAMAGED
- 农业：GROWN_IN, FERTILIZED_BY, APPLIED_TO, RAISED_IN
- 教育：OFFERS, INCLUDES, GRADUATED_FROM, STUDIED, LED_BY, PUBLISHED_IN, AUTHORED_BY
- 文旅：HAS_RATING, PROTECTED_BY, CELEBRATED_IN, CREATED_BY, INHERITED_BY
- 体育：REPRESENTS, PARTICIPATED_IN, WON, HELD_IN
- 法律：HEARD_BY, INVOLVES, APPLIES, IMPOSED_ON
- 通用数值：HAS_VALUE, RANKED, OCCURRED_ON, MEASURED_AT
- 因果：LEADS_TO, CONTRIBUTES_TO, DERIVED_FROM, DEPENDS_ON
- 比较时序：GREATER_THAN, LESS_THAN, EQUALS, BEFORE, AFTER, DURING, SUBSTITUTES
- 组成：HAS_PART, CONSISTS_OF
- 通用：MENTIONED_IN, RECORDED_IN, RELATED_TO, COMPARES_WITH, COLLABORATES_WITH, SUPERVISES

要求：
1. 实体名保持原文写法，不要翻译或改写
2. 如果实体有关键属性（如数值、单位、时间），存入 attributes
3. 关系不要过度提取，只提取文本中明确表达的关系
4. 如果文本主要是数据表格描述，重点提取数值实体和其含义
5. 如果某个实体不属于以上任何预定义类型，自定义一个合理的类型名（英文大驼峰）

输出格式（JSON）：
{{
  "entities": [
    {{"name": "实体名", "type": "类型", "attributes": {{"key": "value"}}}}
  ],
  "relations": [
    {{"head": "实体1", "relation": "关系类型", "tail": "实体2", "attributes": {{}}}}
  ]
}}

只返回JSON，不要其他说明。"""
