import sys
import math
import ROOT
import os
if __name__ == "__main__":
    sys.path.append(os.environ['ANALYSIS_PATH'])

import Common.Utilities as Utilities

scales = ['Up','Down']


def GetUncNameTypes(unc_cfg_dict):
    uncNames = []
    uncNames.extend(list(unc_cfg_dict['norm'].keys()))
    uncNames.extend([unc for unc in unc_cfg_dict['shape']])
    return uncNames

def GetSamplesStuff(sample_cfg_dict,histDir):
    all_samples_list = []
    all_samples_types = {'data':['data'],}
    signals = list(sample_cfg_dict['GLOBAL']['signal_types'])
    for sample in sample_cfg_dict.keys():
        if not os.path.isdir(os.path.join(histDir, sample)): continue
        sample_type = sample_cfg_dict[sample]['sampleType']
        isSignal = False
        if sample_type in signals:
            isSignal = True
            sample_type=sample
        if sample_type not in all_samples_types.keys() :
            all_samples_types[sample_type] = []
        all_samples_types[sample_type].append(sample)
        if isSignal: continue
        if sample_type in all_samples_list: continue
        all_samples_list.append(sample_type)
    return all_samples_list, all_samples_types


def CreateNamesDict(histNamesDict, sample_types, uncName, scales, sample_cfg_dict):
    signals = list(sample_cfg_dict['GLOBAL']['signal_types'])
    for sample_key in sample_types.keys():
        final_sampleKey=f"{sample_key}"
        if sample_key == 'data':
            histNamesDict[final_sampleKey] = (sample_key, 'Central','Central')
            continue
        else:
            if uncName == 'Central':
                histNamesDict[final_sampleKey] = (sample_key, 'Central','Central')
                continue
            else:
                for scale in scales:
                    histName = f"{final_sampleKey}_{uncName}{scale}"
                    histKey = (sample_key,  uncName, scale)
                    histNamesDict[histName] = histKey



def defineP4(df, name):
    df = df.Define(f"{name}_p4", f"ROOT::Math::LorentzVector<ROOT::Math::PtEtaPhiM4D<double>>({name}_pt,{name}_eta,{name}_phi,{name}_mass)")
    return df

def defineAllP4(df):
    for idx in [0,1]:
        df = defineP4(df, f"tau{idx+1}")
        df = defineP4(df, f"b{idx+1}")
        #df = defineP4(df, f"tau{idx+1}_seedingJet")
    return df

def createInvMass(df):
    df = df.Define("tautau_m_vis", "(tau1_p4+tau2_p4).M()")
    df = df.Define("bb_m_vis", "(b1_p4+b2_p4).M()")
    df = df.Define("bbtautau_mass", "(b1_p4+b2_p4+tau1_p4+tau2_p4).M()")
    df = df.Define("dR_tautau", 'ROOT::Math::VectorUtil::DeltaR(tau1_p4, tau2_p4)')
    return df

def RenormalizeHistogram(histogram, norm, include_overflows=True):
    integral = histogram.Integral(0, histogram.GetNbinsX()+1) if include_overflows else histogram.Integral()
    histogram.Scale(norm / integral)

def FixNegativeContributions(histogram):
    correction_factor = 0.

    ss_debug = ""
    ss_negative = ""

    original_Integral = histogram.Integral(0, histogram.GetNbinsX()+1)
    ss_debug += "\nSubtracted hist for '{}'.\n".format(histogram.GetName())
    ss_debug += "Integral after bkg subtraction: {}.\n".format(original_Integral)
    if original_Integral < 0:
        print(ss_debug)
        print("Integral after bkg subtraction is negative for histogram '{}'".format(histogram.GetName()))
        return False,ss_debug, ss_negative

    for n in range(1, histogram.GetNbinsX()+1):
        if histogram.GetBinContent(n) >= 0:
            continue
        prefix = "WARNING" if histogram.GetBinContent(n) + histogram.GetBinError(n) >= 0 else "ERROR"

        ss_negative += "{}: {} Bin {}, content = {}, error = {}, bin limits=[{},{}].\n".format(
            prefix, histogram.GetName(), n, histogram.GetBinContent(n), histogram.GetBinError(n),
            histogram.GetBinLowEdge(n), histogram.GetBinLowEdge(n+1))

        error = correction_factor - histogram.GetBinContent(n)
        new_error = math.sqrt(math.pow(error, 2) + math.pow(histogram.GetBinError(n), 2))
        histogram.SetBinContent(n, correction_factor)
        histogram.SetBinError(n, new_error)

    RenormalizeHistogram(histogram, original_Integral, True)
    return True, ss_debug, ss_negative

class DataFrameBuilderBase:
    def CreateColumnTypes(self):
        colNames = [str(c) for c in self.df.GetColumnNames()]
        entryIndexIdx = colNames.index("entryIndex")
        colNames[entryIndexIdx], colNames[0] = colNames[0], colNames[entryIndexIdx]
        self.colNames = colNames
        self.colTypes = [str(self.df.GetColumnType(c)) for c in self.colNames]

    def __init__(self, df):
        self.df = df
        self.colNames=[]
        self.colTypes=[]
        self.var_list = []
        self.CreateColumnTypes()

    def CreateFromDelta(self,central_columns,central_col_types):
        var_list =[]
        for var_idx,var_name in enumerate(self.colNames):
            if not var_name.endswith("Diff"):
                continue
            var_name_forDelta = var_name.removesuffix("Diff")
            central_col_idx = central_columns.index(var_name_forDelta)
            if central_columns[central_col_idx]!=var_name_forDelta:
                raise RuntimeError(f"CreateFromDelta: {central_columns[central_col_idx]} != {var_name_forDelta}")
            self.df = self.df.Define(f"{var_name_forDelta}", f"""analysis::FromDelta({var_name},
                                     analysis::GetEntriesMap()[entryIndex]->GetValue<{self.colTypes[var_idx]}>({central_col_idx}) )""")
            var_list.append(f"{var_name_forDelta}")
        for central_col_idx,central_col in enumerate(central_columns):
            if central_col in var_list or central_col in self.colNames: continue
            self.df = self.df.Define(central_col, f"""analysis::GetEntriesMap()[entryIndex]->GetValue<{central_col_types[central_col_idx]}>({central_col_idx})""")


def GetModel(hist_cfg, var):
    x_bins = hist_cfg[var]['x_bins']
    if type(hist_cfg[var]['x_bins'])==list:
        x_bins_vec = Utilities.ListToVector(x_bins, "double")
        model = ROOT.RDF.TH1DModel("", "", x_bins_vec.size()-1, x_bins_vec.data())
    else:
        n_bins, bin_range = x_bins.split('|')
        start,stop = bin_range.split(':')
        model = ROOT.RDF.TH1DModel("", "",int(n_bins), float(start), float(stop))
    return model


def mkdir(file, path):
    dir_names = path.split('/')
    current_dir = file
    for n, dir_name in enumerate(dir_names):
        dir_obj = current_dir.Get(dir_name)
        full_name = f'{file.GetPath()}' + '/'.join(dir_names[:n])
        if dir_obj:
            if not dir_obj.IsA().InheritsFrom(ROOT.TDirectory.Class()):
                raise RuntimeError(f'{dir_name} already exists in {full_name} and it is not a directory')
        else:
            dir_obj = current_dir.mkdir(dir_name)
            if not dir_obj:

                raise RuntimeError(f'Failed to create {dir_name} in {full_name}')
        current_dir = dir_obj
    return current_dir




