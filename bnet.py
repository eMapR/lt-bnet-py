import ee
from ltgee import LandTrendr, LandsatComposite, LtCollection, Sentinel2Composite

# Function to make start and end dates for composite time stamps --------------------------------------
def annual_window(start, end):
    year_list = ee.List.sequence(start, end, 1)
    first_date = year_list.map(lambda e: ee.String(ee.Number(e).int()).cat(start_date))
    second_date = year_list.map(lambda e: ee.String(ee.Number(e).int()).cat(end_date))
    dates = first_date.zip(second_date)
    return dates

# Filter a collection function
def filter_collection(year, start_day, end_day, aoi):
    return ee.ImageCollection("NASA/HLS/HLSL30/v002") \
        .filterBounds(aoi) \
        .filterDate(f'{year}-{start_day}', f'{year}-{end_day}') \
        .filter(ee.Filter.lt('CLOUD_COVERAGE', 30))

def get_sr_collection(year, start_day, end_day, aoi):
    sr_collection = filter_collection(year, start_day, end_day, aoi)
    return sr_collection

# Function to combine collections
def get_combined_sr_collection(year, start_day, end_day, aoi):
    hls = get_sr_collection(year, start_day, end_day, aoi)
    return hls

def b2_cloud_mask(image_collection):
    def apply_mask(image):
        cloudMask = image.select('B2').lt(0.02)
        return image.mask(cloudMask)
    # Apply the mask to each image in the collection
    masked_collection = image_collection.map(apply_mask)
    return masked_collection

# Make a medoid composite with equal weight among indices
def mean_mosaic(in_collection, dummy_collection):
    image_count = in_collection.toList(1).length()
    final_collection = ee.ImageCollection(ee.Algorithms.If(image_count.gt(0), in_collection, dummy_collection))
    final_collection = b2_cloud_mask(final_collection)
    return final_collection.mean()

# Function to apply medoid compositing function to a collection
def build_mosaic(year, start_day, end_day, aoi, dummy_collection):
    collection = get_combined_sr_collection(year, start_day, end_day, aoi)
    img = mean_mosaic(collection, dummy_collection).set('system:time_start', ee.Date.fromYMD(year, 8, 1).millis())
    return ee.Image(img).multiply(1000).toUint16()

# Function to build annual mosaic collection
def build_sr_collection(start_year, end_year, start_day, end_day, aoi):
    dummy_collection = ee.ImageCollection([ee.Image([0, 0, 0, 0, 0, 0]).mask(ee.Image(0))])
    imgs = []
    for i in range(start_year, end_year + 1):
        tmp = build_mosaic(i, start_day, end_day, aoi, dummy_collection)
        imgs.append(tmp.set('composite_year', i).set('system:time_start', ee.Date.fromYMD(i, 8, 1).millis()))
    return ee.ImageCollection(imgs)

def get_lt_last_seg_info(lt, idx):
    segInfo = lt.get_segment_data('all', index_flip=True)
    endSeg = segInfo.arraySlice(1, -1, None, 1)
    
    def getLastSeg(img):
        arrRowNames = [['startYear', 'endYear', 'preval', 'postval', 'mag', 'dur', 'rate', 'dsnr']]
        endSegImg = img.arrayProject([0]).arrayFlatten(arrRowNames)
        yod = endSegImg.select('endYear').rename('yod')
        return endSegImg.addBands(yod).select(['yod', 'mag', 'dur', 'preval', 'rate', 'dsnr'])
    
    return getLastSeg(endSeg)

def lcms_forest_mask(start, end, param):
    dataset = ee.ImageCollection('USFS/GTAC/LCMS/v2024-10')
    ts = ee.List.sequence(start, 2024) #<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<HARDCODE TO END YEAR OF LCMS DATASET
    print(ts)
    def query_year(yr):
        img = dataset.filter(ee.Filter.And(
            ee.Filter.eq('system:time_start', ee.Date(ee.String(ee.Number(yr).int().format()).cat(ee.String("-06-01"))).millis()),
            ee.Filter.eq('study_area', param['study_region'])
        )).first().select('Land_Use')
        return img.expression('band == 3', {'band': img})
    
    lcms_agg = ts.map(query_year)
    col = ee.ImageCollection(lcms_agg).sum().gt(0)
    return col


def generate_year_list(start_year, end_year, index):
    year_list = []
    for year in range(start_year, end_year + 1):
        year_list.append(f"{index}_ftv_{year}")
    return year_list


def standardized_lt_image(ltrendr, start_Year, end_Year, fit_index, std_end_year):


    nbr_years = generate_year_list(start_Year, end_Year,'nbr')
    fitted_nbr = ltrendr.data.select(['ftv_nbr_fit']).arrayFlatten([nbr_years]) 
    tcb_years = generate_year_list(start_Year, end_Year,'tcb')
    fitted_tcb = ltrendr.data.select(['ftv_tcb_fit']).arrayFlatten([tcb_years]) 
    tcg_years = generate_year_list(start_Year, end_Year,'tcg')
    fitted_tcg = ltrendr.data.select(['ftv_tcg_fit']).arrayFlatten([tcg_years]) 
    tcw_years = generate_year_list(start_Year, end_Year,'tcw')
    fitted_tcw = ltrendr.data.select(['ftv_tcw_fit']).arrayFlatten([tcw_years]) 

    years = [str(std_end_year - i) for i in [9, 5, 2, 1, 0]]
    nbr_tapered = fitted_nbr.select([f"nbr_ftv_{year}" for year in years], [f"yr_{year}_nbr" for year in years])
    tcb_tapered = fitted_tcb.select([f"tcb_ftv_{year}" for year in years], [f"yr_{year}_tcb" for year in years])
    tcg_tapered = fitted_tcg.select([f"tcg_ftv_{year}" for year in years], [f"yr_{year}_tcg" for year in years])
    tcw_tapered = fitted_tcw.select([f"tcw_ftv_{year}" for year in years], [f"yr_{year}_tcw" for year in years])

    def standardize(fitted):
        mean = fitted.reduce(ee.Reducer.mean())
        return fitted.subtract(mean)

    standardized_nbr = standardize(nbr_tapered).rename([f"yr_{year}_nbr_ltsd" for year in years])
    standardized_tcb = standardize(tcb_tapered).rename([f"yr_{year}_tcb_ltsd" for year in years])
    standardized_tcg = standardize(tcg_tapered).rename([f"yr_{year}_tcg_ltsd" for year in years])
    standardized_tcw = standardize(tcw_tapered).rename([f"yr_{year}_tcw_ltsd" for year in years])

    return standardized_nbr.addBands(standardized_tcb).addBands(standardized_tcg).addBands(standardized_tcw).addBands(nbr_tapered).addBands(tcb_tapered).addBands(tcg_tapered).addBands(tcw_tapered)



def filter_ads(agent, severity, defol, ads_col, all):
    if defol is None and severity is None:
        print("Mortality and defoliation not selected")
        return ads_col
    elif defol is not None and severity is not None:
        print("Both mortality and defoliation selected")
        if all:
            return ads_col.filter(ee.Filter.Or(ee.Filter.eq("DAMCODE", severity), ee.Filter.gt("DAMCODE", defol)))
        else:
            return ads_col.filter(ee.Filter.And(ee.Filter.eq("AGENTCODE", agent), ee.Filter.Or(ee.Filter.eq("DAMCODE", severity), ee.Filter.gt("DAMCODE", defol))))
    elif defol is None:
        print("Only defoliation selected")
        if all:
            return ads_col.filter(ee.Filter.eq("DAMCODE", severity))
        else:
            return ads_col.filter(ee.Filter.And(ee.Filter.eq("AGENTCODE", agent), ee.Filter.eq("DAMCODE", severity)))
    elif severity is None:
        print("Only mortality selected")
        if all:
            return ads_col.filter(ee.Filter.gt("DAMCODE", defol))
        else:
            return ads_col.filter(ee.Filter.And(ee.Filter.eq("AGENTCODE", agent), ee.Filter.gt("DAMCODE", defol)))
    else:
        print("Not sure what happened")

def agg_ads(startyear, focus_year, ads_col):
    start_year = startyear
    end_year = focus_year

    def get_year_band_names(startYear, endYear):
        return [str(i) for i in range(startYear, endYear + 1)]

    year = get_year_band_names(start_year, end_year)

    def create_image(yr):
        return ads_col.reduceToImage(properties=['DAMCODE'], reducer=ee.Reducer.count()).rename(["yr_" + yr])

    image_list = [create_image(yr) for yr in year]
    agent_image = ee.Image(image_list)
    return agent_image.reduce(ee.Reducer.sum()).selfMask()

def dNBR(lt, start, end, indx, ftvLt, roi):
    def get_year_band_names(start, end):
        return ['yr_' + str(i) for i in range(start, end + 1)]

    yearNames = get_year_band_names(start, end)
    yearly_nbr = ltgee.getFittedData(lt, start, end, indx, ftvLt).clip(roi)
    yearly_nbr_pre = yearly_nbr.select(yearNames[:-1])
    yearly_nbr_post = yearly_nbr.select(yearNames[1:])
    return yearly_nbr_post.subtract(yearly_nbr_pre)


def snic_image(img):
    return ee.Algorithms.Image.Segmentation.SNIC(image=img, size=5, compactness=1)

#def SNIC_decline_image(im,std_end_year):
#    years = {i: str(std_end_year - i) for i in [0, 1, 2, 3, 4]}
#    #expression = 'rate > 50 && rate < 160 && dur < 6 && dur > 1'
#    expression = '((nbr_3 - nbr_4 > 75 ) && (nbr_4 - nbr_5 > 100)) || (((tcg_3 - tcg_4 > 100 ) && (tcg_4 - tcg_5 > 100)) && ((tcw_3 - tcw_4 > 100 ) && (tcw_4 - tcw_5 > 100)))'
#    return im.mask(im.expression(expression, {
#        'nbr_1': im.select('nbr_ftv_' + years[4] + '_mean'),
#        'nbr_2': im.select('nbr_ftv_' + years[3] + '_mean'),
#        'nbr_3': im.select('nbr_ftv_' + years[2] + '_mean'),
#        'nbr_4': im.select('nbr_ftv_' + years[1] + '_mean'),
#        'nbr_5': im.select('nbr_ftv_' + years[0] + '_mean'),
#        'tcg_1': im.select('tcg_ftv_' + years[4] + '_mean'),
#        'tcg_2': im.select('tcg_ftv_' + years[3] + '_mean'),
#        'tcg_3': im.select('tcg_ftv_' + years[2] + '_mean'),
#        'tcg_4': im.select('tcg_ftv_' + years[1] + '_mean'),
#        'tcg_5': im.select('tcg_ftv_' + years[0] + '_mean'),
#        'tcw_1': im.select('tcw_ftv_' + years[4] + '_mean'),
#        'tcw_2': im.select('tcw_ftv_' + years[3] + '_mean'),
#        'tcw_3': im.select('tcw_ftv_' + years[2] + '_mean'),
#        'tcw_4': im.select('tcw_ftv_' + years[1] + '_mean'),
#        'tcw_5': im.select('tcw_ftv_' + years[0] + '_mean')
#    }))

#def LTSD_decline_image(im,std_end_year):
#    years = {i: str(std_end_year - i) for i in [0, 1, 2, 3, 4]}
#    expression = '((nbr_3 - nbr_4 > 75 ) && (nbr_4 - nbr_5 > 100)) || (((tcg_3 - tcg_4 > 100 ) && (tcg_4 - tcg_5 > 100)) && ((abs(tcw_3 - tcw_4) > 100 ) && (tcw_4 - tcw_5 > 100))) || ((nbr_4 - nbr_5 > 100) && (tcg_4 - tcg_5 > 100) && (abs(tcw_4 - tcw_5) > 100) )'
#    return im.mask(im.expression(expression, {
#        'nbr_1': im.select('B1_ftv_' + years[4]),
#        'nbr_2': im.select('B1_ftv_' + years[3]),
#        'nbr_3': im.select('B1_ftv_' + years[2]),
#        'nbr_4': im.select('B1_ftv_' + years[1]),
#        'nbr_5': im.select('B1_ftv_' + years[0]),
#        'tcg_1': im.select('B2_ftv_' + years[4]),
#        'tcg_2': im.select('B2_ftv_' + years[3]),
#        'tcg_3': im.select('B2_ftv_' + years[2]),
#        'tcg_4': im.select('B2_ftv_' + years[1]),
#        'tcg_5': im.select('B2_ftv_' + years[0]),
#        'tcw_1': im.select('B3_ftv_' + years[4]),
#        'tcw_2': im.select('B3_ftv_' + years[3]),
#        'tcw_3': im.select('B3_ftv_' + years[2]),
#        'tcw_4': im.select('B3_ftv_' + years[1]),
#        'tcw_5': im.select('B3_ftv_' + years[0])
#    }))

def decline_image(param):
#def decline_image(im, std_end_year, indices, thresholds, logic_template, num_years=5):
    """
    Parameters:
        im (ee.Image): Input image.
        std_end_year (int): Latest year in the image series.
        indices (list): List of index names like ['nbr', 'tcg', 'tcw'].
        thresholds (dict): Dict of thresholds per index, e.g., {'nbr': (75, 100)}.
        logic_template (str): Logic string using placeholders, e.g., '{nbr} || ({tcg} && {tcw})'.
        num_years (int): How many years back to include (default = 5).
    """
    im = ee.Image(param['assetDir'] + param['fitted_img_p'])
    # Build band dictionary
    band_dict = {}
    for index in param['fit']:
        for i in range(param['agent_lookback']):
            key = f"{index}_{i+1}"
            year = param['target'] - (param['agent_lookback'] - 1 - i)
            band_dict[key] = im.select(f"{index}_ftv_{year}")

    # Generate expressions for each index using thresholds
    def decline_expr(index):
        t1, t2 = param['decline_thresholds'].get(index, (100, 100))
        if index == "TCB":
            return f"(({index}_3 - {index}_4 > {t1}) && ({index}_4 - {index}_5 > {t2}))"
        elif index == "TCG":
            return f"(({index}_4 - {index}_3 > {t1}) && ({index}_5 - {index}_4 > {t2}))"
        elif index == "TCW":
            return f"(({index}_4 - {index}_3 > {t1}) && ({index}_5 - {index}_4 > {t2}))"

    # Build expression string by filling in the logic template
    expression = param['decline_template'].format(**{index: decline_expr(index) for index in param['fit']})
    print(expression)
    print(im.bandNames().getInfo())
    #return im.mask(im.expression("((TCW_4 - TCW_5 < 200 ) && (TCW_4 - TCW_5 > 100 )) && ((TCG_4 - TCG_5 < 200 )&&(TCG_4 - TCG_5 > 100 )) || ((TCG_3 - TCG_4 > 100) && (TCG_4 - TCG_5 > 100 )) || ((TCW_3 - TCW_4 > 100) && (TCW_4 - TCW_5 > 100))", band_dict))
    return im.mask(im.expression("((TCG_3 - TCG_4 > 100) && (TCG_4 - TCG_5 > 100 )) || ((TCW_3 - TCW_4 > 100) && (TCW_4 - TCW_5 > 100))", band_dict))

def LTSD_decline_score(param,
                       base_thresholds={'tcb': 70, 'tcg': 70, 'tcw': 70},
                       taper_step=10,
                       min_years_declining=2,
                       return_score=False):
    im = ee.Image(param['assetDir'] + param['fitted_img_p'])
    std_end_year = param['target']

    # Generate 5 consecutive years: oldest (1) to most recent (5)
    years = {i: str(std_end_year - (5 - i)) for i in range(1, 6)}

    # Select bands (note: you're using TCB for "nbr" equivalent here)
    bands = {
        f'tcb_{i}': im.select(f'TCB_ftv_{years[i]}') for i in range(1, 6)
    } | {
        f'tcg_{i}': im.select(f'TCG_ftv_{years[i]}') for i in range(1, 6)
    } | {
        f'tcw_{i}': im.select(f'TCW_ftv_{years[i]}') for i in range(1, 6)
    }

    # Calculate decline per year-pair with tapered thresholds
    diffs = []
    for i in range(1, 5):  # year-pairs: 1-2, 2-3, 3-4, 4-5
        taper = taper_step * (4 - i)  # newest gets 0, oldest gets highest taper

        t_tcb = base_thresholds['tcb'] - taper
        t_tcg = base_thresholds['tcg'] - taper
        t_tcw = base_thresholds['tcw'] - taper

        diff_tcb = bands[f'tcb_{i}'].subtract(bands[f'tcb_{i+1}']).gt(t_tcb)
        diff_tcg = bands[f'tcg_{i}'].subtract(bands[f'tcg_{i+1}']).gt(t_tcg)
        diff_tcw = bands[f'tcw_{i}'].subtract(bands[f'tcw_{i+1}']).abs().gt(t_tcw)


        #year_decline = diff_tcb.And(diff_tcg).And(diff_tcw)
        year_decline = diff_tcg.And(diff_tcw)
        diffs.append(year_decline)

    # Sum yearly decline flags into a score
    decline_score = diffs[0]
    for d in diffs[1:]:
        decline_score = decline_score.add(d)

    # Output: either just the score band, or mask + band
    if return_score:
        return decline_score.rename('decline_score')
    else:
        return im.updateMask(decline_score.gte(min_years_declining)) \
                 .addBands(decline_score.rename('decline_score'))


def get_training_points(recovery, disturbances, roi, referImage, ads_in_roi):
    extract_sample_down = referImage.sampleRegions(collection=disturbances, scale=30, geometries=True, tileScale=10)
    extract_sample_up = referImage.sampleRegions(collection=recovery, scale=30, geometries=True, tileScale=10)
    
    def label_down(feat):
        return feat.set({"label": 1})
    
    def label_up(feat):
        return feat.set({"label": 0})
    
    attri_label_down = extract_sample_down.map(label_down)
    attri_label_up = extract_sample_up.map(label_up)
    return attri_label_down.merge(attri_label_up)


def get_ref_image(lt, ltstartYear, yer, fit, roi):
    tcb_years = generate_year_list(ltstartYear, yer,'tcb')
    fitted_tcb = lt.data.select(['ftv_tcb_fit']).arrayFlatten([tcb_years])
    return fitted_tcb


def tasselCapMask(bnet):

    # Run the LandTrendr algorithm
    targetImage = ee.Image(bnet['LTSDdir']+bnet['fitted_img_p'])
    val = [item.upper() for item in bnet['fit'] if item.lower() == "tcb"]
    tcb = targetImage.select([val[0]+"_ftv_" + str(bnet['target'])])
    
    tcb_mask = tcb.expression('band > '+bnet['brightness_value']+' ? 0 : 1', {'band': tcb}) # 2200

    return tcb_mask

def rename_img(img, target_year):
    yearTarget = str(target_year)
    yearOne = str(target_year - 1)
    yearTwo = str(target_year - 2)
    yearfive = str(target_year - 5)
    yearNine = str(target_year - 9)
    
    return img.select(img.bandNames(), [
        #'clusters','yr_9_nbr_ltsd_mean', 'yr_3_nbr_ltsd_mean', 'yr_2_nbr_ltsd_mean', 'yr_1_nbr_ltsd_mean', 'yr_0_nbr_ltsd_mean',
        #'yr_9_tcb_ltsd_mean', 'yr_5_tcb_ltsd_mean', 'yr_2_tcb_ltsd_mean', 'yr_1_tcb_ltsd_mean', 'yr_0_tcb_ltsd_mean',
        #'yr_9_tcg_ltsd_mean', 'yr_5_tcg_ltsd_mean', 'yr_2_tcg_ltsd_mean', 'yr_1_tcg_ltsd_mean', 'yr_0_tcg_ltsd_mean',
        #'yr_9_tcw_ltsd_mean', 'yr_5_tcw_ltsd_mean', 'yr_2_tcw_ltsd_mean', 'yr_1_tcw_ltsd_mean', 'yr_0_tcw_ltsd_mean',
        #"yr_9_nbr_mean", "yr_5_nbr_mean", "yr_2_nbr_mean", "yr_1_nbr_mean", "yr_0_nbr_mean",
        #"yr_9_tcb_mean", "yr_5_tcb_mean", "yr_2_tcb_mean", "yr_1_tcb_mean", "yr_0_tcb_mean",
        #"yr_9_tcg_mean", "yr_5_tcg_mean", "yr_2_tcg_mean", "yr_1_tcg_mean", "yr_0_tcg_mean",
        #"yr_9_tcw_mean", "yr_5_tcw_mean", "yr_2_tcw_mean", "yr_1_tcw_mean", "yr_0_tcw_mean",
        #"yod_mean", "mag_mean", "dur_mean", "preval_mean", "rate_mean", "dsnr_mean", "seeds"

        'clusters','yr_9_nbr_mean','yr_8_nbr_mean','yr_7_nbr_mean','yr_6_nbr_mean', 'yr_5_nbr_mean','yr_4_nbr_mean', 'yr_3_nbr_mean','yr_2_nbr_mean', 'yr_1_nbr_mean', 'yr_0_nbr_mean',
        'yr_9_tcb_mean','yr_8_tcb_mean','yr_7_tcb_mean','yr_6_tcb_mean', 'yr_5_tcb','yr_4_tcb_mean', 'yr_3_tcb_mean','yr_2_tcb_mean', 'yr_1_tcb_mean', 'yr_0_tcb_mean',
        'yr_9_tcg_mean','yr_8_tcg_mean','yr_7_tcg_mean','yr_6_tcg_mean', 'yr_5_tcg','yr_4_tcg_mean', 'yr_3_tcg_mean','yr_2_tcg_mean', 'yr_1_tcg_mean', 'yr_0_tcg_mean',
        'yr_9_tcw_mean','yr_8_tcw_mean','yr_7_tcw_mean','yr_6_tcw_mean', 'yr_5_tcw','yr_4_tcw_mean', 'yr_3_tcw_mean','yr_2_tcw_mean', 'yr_1_tcw_mean', 'yr_0_tcw_mean','seeds'

    ])

def rename_img_opt3(img, target_year):
    yearTarget = str(target_year)
    yearOne = str(target_year - 1)
    yearTwo = str(target_year - 2)
    yearfive = str(target_year - 5)
    yearNine = str(target_year - 9)
    print(img.bandNames().getInfo())
    return img.select(img.bandNames(), [
        'yr_9_nbr','yr_8_nbr','yr_7_nbr','yr_6_nbr', 'yr_5_nbr','yr_4_nbr', 'yr_3_nbr','yr_2_nbr', 'yr_1_nbr', 'yr_0_nbr',
        'yr_9_tcb','yr_8_tcb','yr_7_tcb','yr_6_tcb', 'yr_5_tcb','yr_4_tcb', 'yr_3_tcb','yr_2_tcb', 'yr_1_tcb', 'yr_0_tcb',
        'yr_9_tcg','yr_8_tcg','yr_7_tcg','yr_6_tcg', 'yr_5_tcg','yr_4_tcg', 'yr_3_tcg','yr_2_tcg', 'yr_1_tcg', 'yr_0_tcg',
        'yr_9_tcw','yr_8_tcw','yr_7_tcw','yr_6_tcw', 'yr_5_tcw','yr_4_tcw', 'yr_3_tcw','yr_2_tcw', 'yr_1_tcw', 'yr_0_tcw'
        #"yod", "mag", "dur", "preval", "rate", "dsnr"
    ])

def rename_ltsd_img(img, target_year):
    yearTarget = str(target_year)
    yearOne = str(target_year - 1)
    yearTwo = str(target_year - 2)
    yearfive = str(target_year - 5)
    yearNine = str(target_year - 9)
    
    return img.select(img.bandNames(), [
        'yr_9_nbr_ltsd', 'yr_5_nbr_ltsd', 'yr_2_nbr_ltsd', 'yr_1_nbr_ltsd', 'yr_0_nbr_ltsd',
        'yr_9_tcb_ltsd', 'yr_5_tcb_ltsd', 'yr_2_tcb_ltsd', 'yr_1_tcb_ltsd', 'yr_0_tcb_ltsd',
        'yr_9_tcg_ltsd', 'yr_5_tcg_ltsd', 'yr_2_tcg_ltsd', 'yr_1_tcg_ltsd', 'yr_0_tcg_ltsd',
        'yr_9_tcw_ltsd', 'yr_5_tcw_ltsd', 'yr_2_tcw_ltsd', 'yr_1_tcw_ltsd', 'yr_0_tcw_ltsd',
        "yr_9_nbr", "yr_5_nbr", "yr_2_nbr", "yr_1_nbr", "yr_0_nbr",
        "yr_9_tcb", "yr_5_tcb", "yr_2_tcb", "yr_1_tcb", "yr_0_tcb",
        "yr_9_tcg", "yr_5_tcg", "yr_2_tcg", "yr_1_tcg", "yr_0_tcg",
        "yr_9_tcw", "yr_5_tcw", "yr_2_tcw", "yr_1_tcw", "yr_0_tcw",
        "yod", "mag", "dur", "preval", "rate", "dsnr"
    ])

def calc_prop(ads_data, kmeans_data):
    def calculate_proportion(k):
        top = ads_data.getNumber(k) if ads_data.contains(k) else ee.Number(-1)
        bottom = kmeans_data.getNumber(k)
        return top.divide(bottom).multiply(100)

    return kmeans_data.map(calculate_proportion)

def ltcalc(year, feat):
    target = feat.filter(ee.Filter.eq('yod', year))
    target = target.map(lambda fe: fe.set('area', fe.area(1)))
    target = target.map(lambda fe: fe.set('perimeter', fe.perimeter(1)))
    target = target.map(lambda fe: fe.set('rati', fe.getNumber('area').divide(fe.getNumber('perimeter'))))
    return target.filter(ee.Filter.Or(ee.Filter.gt('rati', 20), ee.Filter.gt('area', 9500000)))

#def get_canopy_cover(clip):
#    dataset = ee.ImageCollection('USGS/NLCD_RELEASES/2021_REL/TCC/v2021-4')
#    tcc = dataset.filter(ee.Filter.calendarRange(2021, 2021, 'year')).select('Science_Percent_Tree_Canopy_Cover').filter(ee.Filter.eq("study_area", "CONUS")).first().gt(65).selfMask()
#    return tcc.clip(clip)
