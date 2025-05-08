import importlib.util

import os
import sys

def load_parameters(file_path):
    # Dynamically load the module from the file path
    spec = importlib.util.spec_from_file_location("dynamic_params", file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Check for the dictionary and return it
    if hasattr(module, "param"):
        return module.param
    else:
        raise ValueError("The provided script does not define 'parameters'.")


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
    #im = ee.Image(param['assetDir'] + param['fitted_img_p'])
    # Build band dictionary
    band_dict = {}
    for index in param['fit']:
        for i in range(param['agent_lookback']):
            key = f"{index}_{i+1}"
            year = param['target'] - (param['agent_lookback'] - 1 - i)
            #band_dict[key] = im.select(f"{index}_ftv_{year}")

    # Generate expressions for each index using thresholds
    def decline_expr(index,di):
        t1, t2 = param['decline_thresholds'].get(index, (100, 100))
        if di == -1:
            return f"(({index}_3 - {index}_4 > {t1}) && ({index}_4 - {index}_5 > {t2}))"
        elif di == 1:
            return f"(({index}_4 - {index}_3 > {t1}) && ({index}_5 - {index}_4 > {t2}))"

    # Build expression string by filling in the logic template
    expression = param['decline_template'].format(**{index: decline_expr(index, dis) for index, dis in zip(param['fit'], param['direction_disturbance'])})
    print(expression)
    print(band_dict)
    return 1 #im.mask(im.expression(expression, band_dict))



def main():

    if len(sys.argv) != 2:
        print("Usage: python main.py <parameter script path>")
        sys.exit(1)
    param_file = sys.argv[1]

    param = load_parameters(param_file)

    print(param['fit'])
    print(param['agent_lookback'])
    decline_image(param)

if __name__ == "__main__":
    main()
