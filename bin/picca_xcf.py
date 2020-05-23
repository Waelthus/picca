#!/usr/bin/env python
import scipy as sp
import fitsio
import argparse
from multiprocessing import Pool,Lock,cpu_count,Value

from picca import constants, xcf, io, prep_del, utils
from picca.data import Forest
from picca.utils import userprint

def corr_func(pixels):
    """Send correlation on one processor for a list of healpix

    Args:
        pixels (list of int): list of healpix to compute
            the correlation on.

    Returns:
        cor (list of scipy array): list of array with the
            computed correlation and other attributes.

    """
    xcf.fill_neighs(pixels)
    cor = xcf.xcf(pixels)
    return cor

if __name__ == '__main__':

    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description='Compute the cross-correlation between a catalog of objects and a delta field.')

    parser.add_argument('--out', type=str, default=None, required=True,
        help='Output file name')

    parser.add_argument('--in-dir', type=str, default=None, required=True,
        help='Directory to delta files')

    parser.add_argument('--from-image', type=str, default=None, required=False,
        help='Read delta from image format', nargs='*')

    parser.add_argument('--drq', type=str, default=None, required=True,
        help='Catalog of objects in DRQ format')

    parser.add_argument('--rp-min', type=float, default=-200., required=False,
        help='Min r-parallel [h^-1 Mpc]')

    parser.add_argument('--rp-max', type=float, default=200., required=False,
        help='Max r-parallel [h^-1 Mpc]')

    parser.add_argument('--rt-max', type=float, default=200., required=False,
        help='Max r-transverse [h^-1 Mpc]')

    parser.add_argument('--np', type=int, default=100, required=False,
        help='Number of r-parallel bins')

    parser.add_argument('--nt', type=int, default=50, required=False,
        help='Number of r-transverse bins')

    parser.add_argument('--z-min-obj', type=float, default=None, required=False,
        help='Min redshift for object field')

    parser.add_argument('--z-max-obj', type=float, default=None, required=False,
        help='Max redshift for object field')

    parser.add_argument('--z-cut-min', type=float, default=0., required=False,
        help='Use only pairs of forest x object with the mean of the last absorber \
        redshift and the object redshift larger than z-cut-min')

    parser.add_argument('--z-cut-max', type=float, default=10., required=False,
        help='Use only pairs of forest x object with the mean of the last absorber \
        redshift and the object redshift smaller than z-cut-max')

    parser.add_argument('--lambda-abs', type=str, default='LYA', required=False,
        help='Name of the absorption in picca.constants defining the redshift of the delta')

    parser.add_argument('--z-ref', type=float, default=2.25, required=False,
        help='Reference redshift')

    parser.add_argument('--z-evol-del', type=float, default=2.9, required=False,
        help='Exponent of the redshift evolution of the delta field')

    parser.add_argument('--z-evol-obj', type=float, default=1., required=False,
        help='Exponent of the redshift evolution of the object field')

    parser.add_argument('--fid-Om', type=float, default=0.315, required=False,
        help='Omega_matter(z=0) of fiducial LambdaCDM cosmology')

    parser.add_argument('--fid-Or', type=float, default=0., required=False,
        help='Omega_radiation(z=0) of fiducial LambdaCDM cosmology')

    parser.add_argument('--fid-Ok', type=float, default=0., required=False,
        help='Omega_k(z=0) of fiducial LambdaCDM cosmology')

    parser.add_argument('--fid-wl', type=float, default=-1., required=False,
        help='Equation of state of dark energy of fiducial LambdaCDM cosmology')

    parser.add_argument('--no-project', action='store_true', required=False,
        help='Do not project out continuum fitting modes')

    parser.add_argument('--no-remove-mean-lambda-obs', action='store_true', required=False,
        help='Do not remove mean delta versus lambda_obs')

    parser.add_argument('--nside', type=int, default=16, required=False,
        help='Healpix nside')

    parser.add_argument('--nproc', type=int, default=None, required=False,
        help='Number of processors')

    parser.add_argument('--nspec', type=int, default=None, required=False,
        help='Maximum number of spectra to read')

    parser.add_argument('--shuffle-distrib-obj-seed', type=int, default=None, required=False,
        help='Shuffle the distribution of objects on the sky following the given seed. Do not shuffle if None')

    parser.add_argument('--shuffle-distrib-forest-seed', type=int, default=None, required=False,
        help='Shuffle the distribution of forests on the sky following the given seed. Do not shuffle if None')

    args = parser.parse_args()

    if args.nproc is None:
        args.nproc = cpu_count()//2

    xcf.r_par_max = args.rp_max
    xcf.r_par_min = args.rp_min
    xcf.z_cut_max = args.z_cut_max
    xcf.z_cut_min = args.z_cut_min
    xcf.r_trans_max = args.rt_max
    xcf.num_bins_r_par = args.np
    xcf.num_bins_r_trans = args.nt
    xcf.nside = args.nside
    xcf.lambda_abs = constants.ABSORBER_IGM[args.lambda_abs]

    cosmo = constants.Cosmo(Om=args.fid_Om,Or=args.fid_Or,Ok=args.fid_Ok,wl=args.fid_wl)

    ### Read deltas
    dels, ndels, zmin_pix, zmax_pix = io.read_deltas(args.in_dir, args.nside, xcf.lambda_abs,
        args.z_evol_del, args.z_ref, cosmo=cosmo,max_num_spec=args.nspec,no_project=args.no_project,
        from_image=args.from_image)
    xcf.npix = len(dels)
    xcf.dels = dels
    xcf.ndels = ndels
    userprint("")
    userprint("done, npix = {}\n".format(xcf.npix))

    ### Remove <delta> vs. lambda_obs
    if not args.no_remove_mean_lambda_obs:
        Forest.delta_log_lambda = None
        for p in xcf.dels:
            for d in xcf.dels[p]:
                delta_log_lambda = sp.asarray([d.log_lambda[ii]-d.log_lambda[ii-1] for ii in range(1,d.log_lambda.size)]).min()
                if Forest.delta_log_lambda is None:
                    Forest.delta_log_lambda = delta_log_lambda
                else:
                    Forest.delta_log_lambda = min(delta_log_lambda,Forest.delta_log_lambda)
        Forest.log_lambda_min  = sp.log10( (zmin_pix+1.)*xcf.lambda_abs )-Forest.delta_log_lambda/2.
        Forest.log_lambda_max  = sp.log10( (zmax_pix+1.)*xcf.lambda_abs )+Forest.delta_log_lambda/2.
        log_lambda,mean_delta, wst   = prep_del.stack(xcf.dels, stack_from_deltas=True)
        for p in xcf.dels:
            for d in xcf.dels[p]:
                bins = ((d.log_lambda-Forest.log_lambda_min)/Forest.delta_log_lambda+0.5).astype(int)
                d.delta -= mean_delta[bins]

    ### Find the redshift range
    if (args.z_min_obj is None):
        dmin_pix = cosmo.get_r_comov(zmin_pix)
        dmin_obj = max(0.,dmin_pix+xcf.r_par_min)
        args.z_min_obj = cosmo.distance_to_redshift(dmin_obj)
        userprint("\r z_min_obj = {}\r".format(args.z_min_obj),end="")
    if (args.z_max_obj is None):
        dmax_pix = cosmo.get_r_comov(zmax_pix)
        dmax_obj = max(0.,dmax_pix+xcf.r_par_max)
        args.z_max_obj = cosmo.distance_to_redshift(dmax_obj)
        userprint("\r z_max_obj = {}\r".format(args.z_max_obj),end="")

    ### Read objects
    objs,zmin_obj = io.read_objects(args.drq, args.nside, args.z_min_obj, args.z_max_obj,\
                                args.z_evol_obj, args.z_ref,cosmo)

    if not args.shuffle_distrib_obj_seed is None:
        objs = utils.shuffle_distrib_forests(objs,args.shuffle_distrib_obj_seed)
    if not args.shuffle_distrib_forest_seed is None:
        xcf.dels = utils.shuffle_distrib_forests(xcf.dels,
            args.shuffle_distrib_forest_seed)

    userprint("")
    xcf.objs = objs

    ###
    xcf.ang_max = utils.compute_ang_max(cosmo,xcf.r_trans_max,zmin_pix,zmin_obj)



    xcf.counter = Value('i',0)

    xcf.lock = Lock()
    cpu_data = {}
    for p in list(dels.keys()):
        cpu_data[p] = [p]

    pool = Pool(processes=args.nproc)

    cfs = pool.map(corr_func,sorted(list(cpu_data.values())))
    pool.close()

    cfs=sp.array(cfs)
    wes=cfs[:,0,:]
    rps=cfs[:,2,:]
    rts=cfs[:,3,:]
    zs=cfs[:,4,:]
    nbs=cfs[:,5,:].astype(sp.int64)
    cfs=cfs[:,1,:]
    hep=sp.array(sorted(list(cpu_data.keys())))

    cut      = (wes.sum(axis=0)>0.)
    rp       = (rps*wes).sum(axis=0)
    rp[cut] /= wes.sum(axis=0)[cut]
    rt       = (rts*wes).sum(axis=0)
    rt[cut] /= wes.sum(axis=0)[cut]
    z        = (zs*wes).sum(axis=0)
    z[cut]  /= wes.sum(axis=0)[cut]
    nb = nbs.sum(axis=0)

    out = fitsio.FITS(args.out,'rw',clobber=True)
    head = [ {'name':'RPMIN','value':xcf.r_par_min,'comment':'Minimum r-parallel [h^-1 Mpc]'},
        {'name':'RPMAX','value':xcf.r_par_max,'comment':'Maximum r-parallel [h^-1 Mpc]'},
        {'name':'RTMAX','value':xcf.r_trans_max,'comment':'Maximum r-transverse [h^-1 Mpc]'},
        {'name':'NP','value':xcf.num_bins_r_par,'comment':'Number of bins in r-parallel'},
        {'name':'NT','value':xcf.num_bins_r_trans,'comment':'Number of bins in r-transverse'},
        {'name':'ZCUTMIN','value':xcf.z_cut_min,'comment':'Minimum redshift of pairs'},
        {'name':'ZCUTMAX','value':xcf.z_cut_max,'comment':'Maximum redshift of pairs'},
        {'name':'NSIDE','value':xcf.nside,'comment':'Healpix nside'}
    ]
    out.write([rp,rt,z,nb],names=['RP','RT','Z','NB'],
        comment=['R-parallel','R-transverse','Redshift','Number of pairs'],
        units=['h^-1 Mpc','h^-1 Mpc','',''],
        header=head,extname='ATTRI')

    head2 = [{'name':'HLPXSCHM','value':'RING','comment':'Healpix scheme'}]
    out.write([hep,wes,cfs],names=['HEALPID','WE','DA'],
        comment=['Healpix index', 'Sum of weight', 'Correlation'],
        header=head2,extname='COR')

    out.close()
